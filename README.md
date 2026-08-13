# actionguard

**Let a language model decide, without letting it act.**

A small, dependency-free Python layer for systems where a wrong model output
costs money — advertising budgets, pricing, inventory, refunds.

The design is one asymmetry: **the model chooses from a set the code built, and
cites only figures the code computed.** It never constructs an identifier, a
number, or an action kind of its own.

```bash
git clone https://github.com/catonfiree-ja/llm-action-guard
cd llm-action-guard
pip install -e ".[dev]"
python examples/demo.py     # no API key, no network
pytest                      # 117 tests
```

---

## Why not just write a careful prompt

A prompt is a request, and a model is free to decline it. Three things happen
often enough to design around:

1. it names an entity that does not exist — a plausible-looking id it invented
2. it proposes a number far outside anything reasonable
3. it answers differently to the same question five minutes later

None of those are defects; they are properties. So every constraint lives in
code, and model output is treated like input from a stranger: parsed, checked,
and discarded when it does not fit.

The demo ships a deliberately badly-behaved fake model that does all four
common misbehaviours at once. Running it gives:

```
Checking the prose for figures that were never in the data:
  fabricated figures: ['4.2']

Accepted:
  stop c3
  set_budget c2 -> 600
Refused:
  'start' is permanently forbidden
  target_id 'c9' was not offered — the model may only choose among ids it was given
```

The budget was clamped from the proposed 250,000 to 600 (+20% of the current
500) rather than rejected, so one bad generation cannot stall the run.

---

## The four pieces

### 1. `ActionGuard` — the model picks, it does not build

```python
guard = ActionGuard(
    specs=[
        ActionSpec("stop"),
        ActionSpec("set_budget", needs_value=True,
                   min_value=50, max_value=100_000, max_change_ratio=0.20),
    ],
    offered_ids=[r["id"] for r in rows],
    current_values={r["id"]: r["budget"] for r in rows},
)
actions, refused = guard.validate_all(model_reply["actions"])
```

An action kind outside the allow-list is refused. A target id that was not
offered is refused. A value is always clamped by code, never taken as given.

There is also a permanent `FORBIDDEN_KINDS` set — `start`, `launch`, `create`,
`delete` and friends — checked **before** the allow-list, and rejected at
construction time if someone tries to permit one. An allow-list is a thing
people edit; this is the thing that stops a careless edit from becoming a
spending capability.

> In an ads system the irreversible moment is *starting* to spend. That is not
> a capability a model should be able to hold, so it is not in the option set
> at all — no output can produce it.

### 2. `Evidence` — code does the arithmetic, the model does the sentence

A model asked to both analyse and explain will produce a figure that reads as
if it came from your data and did not. Nothing downstream catches it, because a
wrong number and a right number are the same shape.

```python
evidence = Evidence(rows, notes={"window_days": 30})
prompt   = f"{instructions}\n\n{evidence.prompt_block()}"
...
evidence.assert_grounded(model_reply["summary"])   # raises on invented figures
```

`prompt_block()` carries the table and the one instruction that matters.
`unsupported_numbers()` checks the way back — any figure in the prose that is
not in the table, within a 0.5% rounding tolerance, is flagged.

Number parsing is explicit about separators, because getting it backwards is a
100–1000× error:

| written | read as | rule |
|---|---|---|
| `8,412` | 8412 | lone separator + exactly 3 digits = thousands |
| `1.250` | 1250 | same rule, other convention |
| `1,250.50` | 1250.50 | two separators — the last is the decimal |
| `1.250,50` | 1250.50 | same |
| `c1`, `v1.2.3` | *not a number* | digits welded to a word are identifiers |

### 3. `ConfidenceGate` — refuse to judge on thin data, with one exception

The obvious gate is a minimum sample. A naive one has a hole that costs real
money: something that spent a lot and produced almost nothing has a tiny sample
*because it is failing*, so a successes-only gate skips exactly the item that
most needs stopping.

So confidence arrives two ways — enough successes to trust a rate, **or** enough
exposure that near-zero successes is itself the finding.

```python
gate = ConfidenceGate(min_successes=30, min_exposure=5_000, min_cost=500)
gate.check(successes=1, exposure=20_000, cost=1_500)
# Verdict(trusted=True, reason='only 1 results from 20000 impressions
#         at a cost of 1500 — the absence is the finding')
```

Any significance gate over a funnel needs the second door. Without it the
failure mode is silent and always in the same direction.

### 4. `Outcome` — "no data" and "I could not read the data" are different

A fetch fails, a helper swallows the error and returns `[]`, and every layer
above reports "nothing to do" in perfectly calm language.

```python
Outcome.empty()               # the source answered: nothing
Outcome.unknown("timeout")    # the source did not answer
```

`unwrap()` raises rather than guessing; a fallback has to be typed out with
`unwrap_or([...])`. `unknown()` requires a reason, because an unexplained
failure is how the bug comes back.

Plus `JsonlAudit`: append-only, `fsync`ed, thread-safe, atomically trimmed, and
it records **refusals as well as actions** — otherwise a week of forbidden
proposals looks identical to a quiet week.

---

## Where this came from

Written after building an internal tool where a model wrote the analysis and a
human pressed every button that spent money. This repository is a clean-room
rewrite of the *pattern* only — no employer code, data, prompts or figures
appear here, and every number in the demo and the tests is invented.

## Scope and honesty

- **Does not** call any model vendor. Bring your own client; this validates
  whatever comes back.
- **Does not** make a model correct. It makes a wrong model survivable.
- `Evidence` catches figures that are absent from the table. It cannot catch a
  wrong *claim* made entirely in words.
- `FORBIDDEN_KINDS` defaults suit advertising and spending systems; other
  domains should set their own.
- Python 3.10+, no runtime dependencies. 117 tests, 92% line coverage, CI on
  Linux and Windows across Python 3.10-3.13.

MIT licensed.
