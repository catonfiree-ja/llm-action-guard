import pytest

from actionguard import ConfidenceGate

GATE = ConfidenceGate(min_successes=30, min_exposure=5_000, min_cost=500)


def test_enough_successes_is_trusted():
    assert GATE.check(successes=40, exposure=900, cost=100)


def test_thin_data_is_refused():
    v = GATE.check(successes=2, exposure=80, cost=50)
    assert not v and "too thin" in v.reason


def test_the_expensive_failure_is_still_judged():
    """The hole a naive gate leaves.

    Something that spent a lot and produced almost nothing has a tiny sample
    *because it is failing*. A successes-only gate would skip exactly the item
    that most needs stopping.
    """
    v = GATE.check(successes=1, exposure=20_000, cost=1_500)
    assert v and "the absence is the finding" in v.reason


def test_high_exposure_without_the_cost_floor_is_not_enough():
    """Free impressions are not evidence of waste — spending is."""
    assert not GATE.check(successes=1, exposure=20_000, cost=0)


def test_boundaries_are_inclusive():
    assert GATE.check(successes=30, exposure=0, cost=0)
    assert GATE.check(successes=0, exposure=5_000, cost=500)


def test_zero_everything_is_refused():
    assert not GATE.check(successes=0, exposure=0, cost=0)


def test_negative_thresholds_are_rejected():
    """A negative threshold matches everything — it would pass the whole account."""
    with pytest.raises(ValueError):
        ConfidenceGate(min_successes=-1)


class TestFilter:
    ROWS = [
        {"id": "a", "clicks": 100, "impr": 9_000, "cost": 400},   # enough clicks
        {"id": "b", "clicks": 1, "impr": 40, "cost": 20},         # thin
        {"id": "c", "clicks": 2, "impr": 30_000, "cost": 2_000},  # failing loudly
    ]

    def test_splits_and_keeps_the_reason(self):
        keep, skip = GATE.filter(self.ROWS, successes="clicks",
                                 exposure="impr", cost="cost")
        assert {r["id"] for r in keep} == {"a", "c"}
        assert {r["id"] for r in skip} == {"b"}
        assert all("_confidence" in r for r in keep + skip)

    def test_missing_columns_default_to_zero_not_a_crash(self):
        keep, skip = GATE.filter([{"id": "x"}], successes="clicks",
                                 exposure="impr", cost="cost")
        assert not keep and len(skip) == 1

    def test_original_rows_are_not_mutated(self):
        rows = [dict(r) for r in self.ROWS]
        GATE.filter(rows, successes="clicks", exposure="impr", cost="cost")
        assert all("_confidence" not in r for r in rows)
