"""Refuse to judge on data too thin to judge on — with one exception that
matters more than the rule.

The obvious gate is a minimum sample: do not call a segment good or bad on
three clicks. But a naive gate has a hole that costs real money. Consider
something that has spent a lot and produced almost nothing. Its sample is tiny
*because it is failing*, so a clicks-only gate skips it as "not enough data" —
and the single worst performer is the one thing that never gets reviewed.

So confidence arrives two ways:

  * enough successes to trust a rate, or
  * enough exposure that near-zero successes is itself the finding

Any significance gate over a funnel needs the second door. Without it the
failure mode is silent and always in the same direction.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    trusted: bool
    reason: str

    def __bool__(self) -> bool:
        return self.trusted


@dataclass(frozen=True)
class ConfidenceGate:
    """
    >>> gate = ConfidenceGate(min_successes=30, min_exposure=5000, min_cost=500)
    >>> bool(gate.check(successes=40, exposure=900, cost=100))
    True
    >>> bool(gate.check(successes=2, exposure=80, cost=50))
    False
    >>> bool(gate.check(successes=1, exposure=20_000, cost=1_500))  # failing loudly
    True
    """

    min_successes: int = 30
    min_exposure: int = 5_000
    min_cost: float = 0.0

    def __post_init__(self) -> None:
        for name in ("min_successes", "min_exposure", "min_cost"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")

    def check(self, successes: int, exposure: int, cost: float = 0.0) -> Verdict:
        if successes >= self.min_successes:
            return Verdict(True, f"{successes} results is enough to judge a rate")
        if exposure >= self.min_exposure and cost >= self.min_cost:
            return Verdict(
                True,
                f"only {successes} results from {exposure} impressions "
                f"at a cost of {cost:g} — the absence is the finding")
        return Verdict(
            False,
            f"too thin to judge: {successes} results, {exposure} impressions "
            f"(need {self.min_successes} results, or {self.min_exposure} "
            f"impressions with cost at or above {self.min_cost:g})")

    def filter(self, rows: list[dict], *, successes: str, exposure: str,
               cost: str | None = None) -> tuple[list[dict], list[dict]]:
        """Split rows into judgeable and not, keeping the reason on each."""
        keep, skip = [], []
        for r in rows:
            v = self.check(
                int(r.get(successes, 0) or 0),
                int(r.get(exposure, 0) or 0),
                float(r.get(cost, 0) or 0) if cost else 0.0)
            (keep if v.trusted else skip).append({**r, "_confidence": v.reason})
        return keep, skip
