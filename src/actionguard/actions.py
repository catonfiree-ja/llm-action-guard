"""What an action is allowed to be.

The whole design rests on one asymmetry: the model *chooses from* a set the
code built. It never *constructs* anything. Every field below is either picked
from an offered list or clamped into a range by code the model cannot reach.
"""
from __future__ import annotations

from dataclasses import dataclass


class Rejected(Exception):
    """A proposal did not survive validation. Carries a human-readable why."""

    def __init__(self, reason: str, proposal: object = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.proposal = proposal


@dataclass(frozen=True)
class Action:
    """A validated, executable action. Only `ActionGuard` may construct one."""

    kind: str
    target_id: str
    value: float | None = None
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.kind or not self.target_id:
            raise ValueError("kind and target_id are required")


@dataclass(frozen=True)
class ActionSpec:
    """The contract for one permitted action kind.

    `needs_value` distinguishes 'stop this' from 'set the budget to N'. When a
    value is required it is always clamped, never taken as given — a model that
    proposes a 40x budget increase gets a legal number back, not an error, so
    one bad generation cannot stall the whole run.
    """

    kind: str
    needs_value: bool = False
    min_value: float = 0.0
    max_value: float = 0.0
    max_change_ratio: float = 0.0   # e.g. 0.20 -> at most ±20% of current

    def __post_init__(self) -> None:
        # Normalise once, so the construction-time ban, the allow-list key and
        # validate() all agree. Without this, ActionSpec("STOP") is a dead
        # entry and ActionSpec("START") slips past the forbidden check.
        object.__setattr__(self, "kind", str(self.kind).strip().lower())
        if not self.kind:
            raise ValueError("kind is required")
        if self.needs_value and self.max_value <= self.min_value:
            # Defaults are 0.0/0.0. Left alone, every value would clamp to 0 —
            # a silent zeroing of budgets. Fail at startup instead.
            raise ValueError(
                f"{self.kind!r} needs a value, so it needs a real range; got "
                f"min={self.min_value!r} max={self.max_value!r}")
        if self.max_change_ratio < 0:
            raise ValueError("max_change_ratio must not be negative")

    def clamp(self, proposed: float, current: float | None) -> float:
        """Force `proposed` into the legal window.

        The ratio window (±N% of the current value) and the absolute window
        can fail to overlap — a campaign sitting below the absolute floor, for
        instance. An earlier version reopened the full absolute range in that
        case, which turned the tightest situation into the loosest one. Now the
        answer is the point of the ratio window nearest the absolute range, so
        a non-overlap can only ever narrow the outcome.
        """
        lo, hi = self.min_value, self.max_value
        if self.max_change_ratio and current is not None:
            step = abs(current) * self.max_change_ratio
            r_lo, r_hi = current - step, current + step
            lo, hi = max(lo, r_lo), min(hi, r_hi)
            if lo > hi:
                point = min(max(r_lo, self.min_value), self.max_value)
                lo = hi = point
        return max(lo, min(hi, proposed))


# Actions that must never exist, whatever any config or prompt says.
#
# This list is deliberately separate from the allow-list. An allow-list is a
# thing people edit; this is the thing that stops a careless edit from
# mattering. In an ad system the irreversible-money moment is *starting* to
# spend, so nothing that starts spending is grantable — including the quieter
# synonyms, which is how this kind of ban usually leaks.
FORBIDDEN_KINDS = frozenset({
    "start", "launch", "activate", "enable", "resume", "unpause", "restart",
    "reactivate", "run", "go_live", "publish", "approve", "submit",
    "create", "duplicate", "copy", "clone", "delete", "remove", "archive",
})
