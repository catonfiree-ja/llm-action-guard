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


class TestEmptyAndNoneInput:
    """Missing metrics are the normal case for a campaign that just started.
    They must read as 'not enough to judge', never as 'nothing wrong'."""

    def test_filtering_nothing_returns_nothing(self):
        assert GATE.filter([], successes="clicks", exposure="impr",
                           cost="cost") == ([], [])

    def test_null_metrics_count_as_zero_rather_than_crashing(self):
        rows = [{"id": "x", "clicks": None, "impr": None, "cost": None}]
        keep, skip = GATE.filter(rows, successes="clicks", exposure="impr",
                                 cost="cost")
        assert not keep and [r["id"] for r in skip] == ["x"]
        assert "too thin" in skip[0]["_confidence"]

    @pytest.mark.parametrize("blank", [None, "", 0])
    def test_a_blank_cost_cannot_open_the_second_door(self, blank):
        """High exposure alone is not evidence of waste — spending is."""
        rows = [{"id": "x", "clicks": 1, "impr": 30_000, "cost": blank}]
        keep, _ = GATE.filter(rows, successes="clicks", exposure="impr",
                              cost="cost")
        assert not keep

    def test_omitting_the_cost_column_keeps_the_cost_floor_shut(self):
        """`cost=None` means 'no cost data', so a gate with a cost floor must
        refuse rather than assume the floor was met."""
        rows = [{"id": "x", "clicks": 1, "impr": 30_000}]
        keep, skip = GATE.filter(rows, successes="clicks", exposure="impr")
        assert not keep and len(skip) == 1

    def test_an_empty_row_is_skipped_not_trusted(self):
        keep, skip = GATE.filter([{}], successes="clicks", exposure="impr",
                                 cost="cost")
        assert not keep and len(skip) == 1

    def test_an_all_zero_gate_trusts_everything(self):
        """Documented so it is chosen, not stumbled into: thresholds of zero
        are not a gate at all — every empty row passes."""
        assert ConfidenceGate(min_successes=0, min_exposure=0,
                              min_cost=0).check(successes=0, exposure=0)

    def test_the_default_gate_still_refuses_empty_data(self):
        assert not ConfidenceGate().check(successes=0, exposure=0)

    def test_zero_thresholds_are_allowed_only_negatives_are_not(self):
        ConfidenceGate(min_successes=0, min_exposure=0, min_cost=0)
        for kwargs in ({"min_exposure": -1}, {"min_cost": -0.01}):
            with pytest.raises(ValueError):
                ConfidenceGate(**kwargs)
