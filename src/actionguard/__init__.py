"""actionguard — let a language model decide, without letting it act.

A small, dependency-free layer for systems where a wrong model output costs
money: advertising budgets, pricing, inventory, refunds, anything that moves a
number in the real world.

The design in one sentence: **the model chooses from a set the code built, and
cites only figures the code computed.**

    from actionguard import ActionGuard, ActionSpec, Evidence, ConfidenceGate

    evidence = Evidence(rows)                      # code computed these
    prompt   = f"...\n{evidence.prompt_block()}"   # model may cite only these
    guard    = ActionGuard(
        [ActionSpec("stop"),
         ActionSpec("set_budget", needs_value=True,
                    min_value=50, max_value=100_000, max_change_ratio=0.20)],
        offered_ids=[r["id"] for r in rows],
        current_values={r["id"]: r["budget"] for r in rows},
    )

    actions, refused = guard.validate_all(model_json["actions"])
    evidence.assert_grounded(model_json["summary"])

Nothing here talks to a model vendor; bring your own client.
"""
from .actions import Action, ActionSpec, FORBIDDEN_KINDS, Rejected
from .audit import JsonlAudit
from .confidence import ConfidenceGate, Verdict
from .evidence import Evidence, numbers_in
from .guard import ActionGuard
from .outcome import DataUnavailable, Outcome

__all__ = [
    "Action", "ActionGuard", "ActionSpec", "ConfidenceGate", "DataUnavailable",
    "Evidence", "FORBIDDEN_KINDS", "JsonlAudit", "Outcome", "Rejected",
    "Verdict", "numbers_in",
]
__version__ = "0.1.0"
