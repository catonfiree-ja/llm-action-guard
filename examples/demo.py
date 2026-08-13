"""A runnable end-to-end example. No API key, no network, no vendor.

The fake model below is deliberately badly behaved — it does all four things a
real one does on a bad day. Run it and watch every one get stopped:

    python examples/demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from actionguard import (ActionGuard, ActionSpec, ConfidenceGate, Evidence,
                         JsonlAudit, Outcome)

# ---------------------------------------------------------------- 1. the data
# Code fetches and computes. Every figure below came from arithmetic, not prose.
FETCHED = Outcome.ok([
    {"id": "c1", "name": "winter sale", "budget": 1000.0,
     "clicks": 240, "impressions": 96_000, "spend": 7_200.0, "cpc": 30.0},
    {"id": "c2", "name": "retargeting always-on", "budget": 500.0,
     "clicks": 1_500, "impressions": 60_000, "spend": 1_800.0, "cpc": 1.2},
    {"id": "c3", "name": "brand awareness", "budget": 800.0,
     "clicks": 2, "impressions": 25_000, "spend": 1_600.0, "cpc": 800.0},
    {"id": "c4", "name": "new launch", "budget": 300.0,
     "clicks": 3, "impressions": 400, "spend": 60.0, "cpc": 20.0},
])

rows = FETCHED.unwrap()

# ------------------------------------------------------- 2. who may be judged
gate = ConfidenceGate(min_successes=30, min_exposure=5_000, min_cost=500)
judgeable, skipped = gate.filter(
    list(rows), successes="clicks", exposure="impressions", cost="spend")

print("Judgeable:")
for r in judgeable:
    print(f"  {r['id']}  {r['_confidence']}")
print("Held back:")
for r in skipped:
    print(f"  {r['id']}  {r['_confidence']}")
# c3 is judgeable despite 2 clicks: 25,000 impressions and 1,600 spent means
# the near-absence of clicks *is* the finding. c4 is correctly held back.

# ------------------------------------------------------------ 3. the contract
evidence = Evidence(
    [{k: r[k] for k in ("id", "clicks", "impressions", "spend", "cpc")}
     for r in judgeable],
    notes={"window_days": 30},
)

guard = ActionGuard(
    specs=[
        ActionSpec("stop"),
        ActionSpec("set_budget", needs_value=True, min_value=50,
                   max_value=100_000, max_change_ratio=0.20),
    ],
    offered_ids=[r["id"] for r in judgeable],
    current_values={r["id"]: r["budget"] for r in judgeable},
)

print("\nPrompt the model actually receives:\n")
print(evidence.prompt_block())


# ------------------------------------------------------------- 4. a bad model
def fake_model(_prompt: str) -> dict:
    """Four realistic misbehaviours in one response."""
    return {
        "summary": (
            "c3 spent 1600 for 2 clicks and should stop. "
            "c1 is running at 4.2 per click, which is acceptable."   # invented
        ),
        "actions": [
            {"kind": "stop", "target_id": "c3",
             "rationale": "25000 impressions, 2 clicks"},
            {"kind": "start", "target_id": "c2",                     # forbidden
             "rationale": "it is cheap, let us scale it"},
            {"kind": "set_budget", "target_id": "c9",                # invented id
             "value": 5000, "rationale": "looks promising"},
            {"kind": "set_budget", "target_id": "c2",                # absurd value
             "value": 250_000, "rationale": "scale hard"},
        ],
    }


reply = fake_model(evidence.prompt_block())

# ------------------------------------------------------------- 5. the gauntlet
audit = JsonlAudit(Path(__file__).with_name("demo-audit.jsonl"))

print("\nChecking the prose for figures that were never in the data:")
fabricated = evidence.unsupported_numbers(reply["summary"])
print(f"  fabricated figures: {[f'{n:g}' for n in fabricated] or 'none'}")

actions, refused = guard.validate_all(reply["actions"])

print("\nAccepted:")
for a in actions:
    detail = f" -> {a.value:g}" if a.value is not None else ""
    print(f"  {a.kind} {a.target_id}{detail}")
    audit.accepted(a)

print("Refused:")
for r in refused:
    print(f"  {r.reason}")
    audit.rejected(r.reason, r.proposal)

print(f"\nAudit trail: {audit.path}  ({len(list(audit.read()))} entries)")
print(f"\n{len(actions)} of {len(reply['actions'])} proposals survived. "
      "The budget on c2 was clamped\nfrom 250,000 to 600 (+20% of 500), "
      "one invented figure was caught in the prose,\nand nothing started "
      "spending.")
