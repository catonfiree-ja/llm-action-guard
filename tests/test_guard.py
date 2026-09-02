import pytest

from actionguard import ActionGuard, ActionSpec, FORBIDDEN_KINDS, Rejected

SPECS = [
    ActionSpec("stop"),
    ActionSpec("set_budget", needs_value=True, min_value=50,
               max_value=100_000, max_change_ratio=0.20),
]


def make(offered=("c1", "c2"), current=None):
    return ActionGuard(SPECS, offered_ids=list(offered),
                       current_values=current or {"c1": 1_000.0, "c2": 500.0})


def test_accepts_a_well_formed_proposal():
    action = make().validate({"kind": "stop", "target_id": "c1",
                              "rationale": "no clicks in 14 days"})
    assert (action.kind, action.target_id) == ("stop", "c1")
    assert action.value is None


def test_rejects_an_invented_target_id():
    """The most common real failure: a plausible id that does not exist."""
    with pytest.raises(Rejected, match="was not offered"):
        make().validate({"kind": "stop", "target_id": "c_does_not_exist"})


def test_rejects_an_action_kind_outside_the_allow_list():
    with pytest.raises(Rejected, match="not an allowed action"):
        make().validate({"kind": "set_bid", "target_id": "c1", "value": 5})


@pytest.mark.parametrize("kind", sorted(FORBIDDEN_KINDS))
def test_forbidden_kinds_can_never_pass(kind):
    with pytest.raises(Rejected, match="permanently forbidden"):
        make().validate({"kind": kind, "target_id": "c1"})


def test_forbidden_kinds_cannot_be_granted_by_config():
    """A careless allow-list edit must not become a spending capability."""
    with pytest.raises(ValueError, match="permanently forbidden"):
        ActionGuard([ActionSpec("launch")], offered_ids=["c1"])


def test_forbidden_check_precedes_the_allow_list():
    guard = make()
    guard._specs["start"] = ActionSpec("start")      # simulate a bad mutation
    with pytest.raises(Rejected, match="permanently forbidden"):
        guard.validate({"kind": "start", "target_id": "c1"})


def test_empty_offer_list_is_refused_not_treated_as_allow_all():
    with pytest.raises(ValueError, match="empty"):
        ActionGuard(SPECS, offered_ids=[])


class TestValueClamping:
    def test_absurd_increase_is_clamped_not_rejected(self):
        """One bad generation should not stall the run."""
        action = make().validate(
            {"kind": "set_budget", "target_id": "c1", "value": 9_999_999})
        assert action.value == pytest.approx(1_200.0)      # +20% of 1000

    def test_absurd_decrease_is_clamped(self):
        action = make().validate(
            {"kind": "set_budget", "target_id": "c1", "value": -5})
        assert action.value == pytest.approx(800.0)        # -20% of 1000

    def test_absolute_floor_wins_over_the_ratio(self):
        action = make(current={"c1": 55.0}).validate(
            {"kind": "set_budget", "target_id": "c1", "value": 1})
        assert action.value >= 50

    def test_reasonable_value_passes_untouched(self):
        action = make().validate(
            {"kind": "set_budget", "target_id": "c1", "value": 1_100})
        assert action.value == pytest.approx(1_100.0)

    @pytest.mark.parametrize("bad", ["", None, "abc", [], {}, float("nan"),
                                     float("inf")])
    def test_non_numeric_and_non_finite_values_are_rejected(self, bad):
        with pytest.raises(Rejected):
            make().validate({"kind": "set_budget", "target_id": "c1",
                             "value": bad})


class TestBatch:
    def test_one_bad_proposal_does_not_discard_the_good_ones(self):
        kept, dropped = make().validate_all([
            {"kind": "stop", "target_id": "c1"},
            {"kind": "stop", "target_id": "ghost"},
            {"kind": "stop", "target_id": "c2"},
        ])
        assert [a.target_id for a in kept] == ["c1", "c2"]
        assert len(dropped) == 1

    def test_duplicates_are_dropped(self):
        kept, dropped = make().validate_all([
            {"kind": "stop", "target_id": "c1"},
            {"kind": "stop", "target_id": "c1"},
        ])
        assert len(kept) == 1 and len(dropped) == 1

    @pytest.mark.parametrize("junk", [None, [], [None], ["a string"], [42]])
    def test_malformed_input_never_raises(self, junk):
        kept, _ = make().validate_all(junk)
        assert kept == []


def test_kind_matching_is_case_and_space_insensitive():
    action = make().validate({"kind": "  STOP ", "target_id": "c1"})
    assert action.kind == "stop"


def test_rationale_is_truncated_not_trusted():
    action = make().validate({"kind": "stop", "target_id": "c1",
                              "rationale": "x" * 5_000})
    assert len(action.rationale) == 500


class TestEmptyAndNoneInput:
    """A model that produces nothing must fail the same way as one that
    produces nonsense: refused, in code, with a reason worth logging."""

    @pytest.mark.parametrize("proposal", [None, "", 0, [], ()])
    def test_a_non_object_proposal_is_refused(self, proposal):
        with pytest.raises(Rejected, match="not an object"):
            make().validate(proposal)

    def test_an_empty_object_names_no_action(self):
        with pytest.raises(Rejected, match="not an allowed action"):
            make().validate({})

    @pytest.mark.parametrize("kind", ["", "   ", None])
    def test_a_blank_or_missing_kind_is_not_an_allowed_action(self, kind):
        with pytest.raises(Rejected, match="not an allowed action"):
            make().validate({"kind": kind, "target_id": "c1"})

    @pytest.mark.parametrize("target", ["", "   ", None])
    def test_a_blank_or_missing_target_was_never_offered(self, target):
        """An absent id must not collapse into 'whichever one you like'."""
        with pytest.raises(Rejected, match="was not offered"):
            make().validate({"kind": "stop", "target_id": target})

    def test_a_missing_value_is_refused_for_a_kind_that_needs_one(self):
        with pytest.raises(Rejected, match="requires a numeric value"):
            make().validate({"kind": "set_budget", "target_id": "c1"})

    def test_a_missing_rationale_stays_a_short_string(self):
        """It lands in the audit log, so it must never be None or unbounded."""
        for proposal in ({"kind": "stop", "target_id": "c1"},
                         {"kind": "stop", "target_id": "c1", "rationale": None}):
            action = make().validate(proposal)
            assert isinstance(action.rationale, str)
            assert len(action.rationale) <= 500

    def test_no_specs_means_nothing_is_decidable(self):
        """An empty allow-list allows nothing — it is not a wildcard."""
        guard = ActionGuard([], offered_ids=["c1"])
        assert guard.allowed_kinds == ()
        with pytest.raises(Rejected, match="not an allowed action"):
            guard.validate({"kind": "stop", "target_id": "c1"})

    @pytest.mark.parametrize("offered", [None, [], ()])
    def test_an_absent_offer_list_is_refused_at_construction(self, offered):
        with pytest.raises(ValueError, match="empty"):
            ActionGuard(SPECS, offered_ids=offered)

    @pytest.mark.parametrize("current", [None, {}, {"c1": None}])
    def test_an_unknown_current_value_falls_back_to_the_absolute_ceiling(
            self, current):
        """No baseline means no ratio window — but never an open window."""
        action = ActionGuard(SPECS, offered_ids=["c1"],
                             current_values=current).validate(
            {"kind": "set_budget", "target_id": "c1", "value": 9_999_999})
        assert action.value == pytest.approx(100_000.0)

    def test_a_current_value_of_zero_clamps_to_the_floor_not_to_zero(self):
        """±20% of 0 is 0. Taken literally that zeroes the budget, so the
        absolute floor has to win."""
        action = make(current={"c1": 0.0}).validate(
            {"kind": "set_budget", "target_id": "c1", "value": 9_999_999})
        assert action.value == pytest.approx(50.0)

    def test_an_empty_batch_is_not_an_error(self):
        assert make().validate_all([]) == ([], [])

    def test_a_null_batch_is_not_an_error(self):
        assert make().validate_all(None) == ([], [])

    @pytest.mark.parametrize("junk", ["", "stop"])
    def test_a_string_batch_yields_one_rejection_not_one_per_letter(self, junk):
        kept, dropped = make().validate_all(junk)
        assert kept == [] and len(dropped) == 1
        assert "not a list" in dropped[0].reason

    def test_empty_proposals_in_a_batch_are_dropped_with_a_reason(self):
        kept, dropped = make().validate_all([
            None, {}, {"kind": "stop", "target_id": "c1"}])
        assert [a.target_id for a in kept] == ["c1"]
        assert len(dropped) == 2
        assert all(d.reason for d in dropped)


class TestEmptySpecKind:
    @pytest.mark.parametrize("kind", ["", "   "])
    def test_a_blank_spec_kind_is_refused(self, kind):
        """A nameless spec would sit in the allow-list unreachable, and every
        proposal with a missing kind would match it."""
        with pytest.raises(ValueError, match="kind is required"):
            ActionSpec(kind)

    def test_a_value_kind_without_a_range_is_refused(self):
        """Defaults are 0/0 — left alone, every budget clamps to zero."""
        with pytest.raises(ValueError, match="needs a real range"):
            ActionSpec("set_budget", needs_value=True)
