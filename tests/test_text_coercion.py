"""Every untrusted field read as text must treat null as an absence.

`dict.get(key, default)` returns the default only when the key is *absent*, so
`{"kind": null}` slips past it, reaches `str()`, and becomes the word "None".
#2 fixed that for `rationale`; the same shape was left in three other places:
`kind`, `target_id`, and the evidence table handed to the model. All four now
go through `text_field`, and this file holds it to that at each site.

The rule being defended is narrow on purpose: **null is empty, falsy is not.**
`or ""` would close the null hole and quietly swallow `0` and `False` with it.
"""
import pytest

from actionguard import ActionGuard, ActionSpec, Evidence, Rejected
from actionguard.text import text_field

SPECS = [
    ActionSpec("stop"),
    ActionSpec("set_budget", needs_value=True, min_value=50,
               max_value=100_000, max_change_ratio=0.20),
]


def make(offered_ids=("c1", "c2")):
    return ActionGuard(SPECS, offered_ids=list(offered_ids),
                       current_values={"c1": 1_000.0, "c2": 500.0})


class TestTheHelper:
    """One coercion, so there is one behaviour to reason about."""

    @pytest.mark.parametrize("field", ["kind", "target_id", "rationale"])
    def test_a_null_value_reads_as_empty(self, field):
        assert text_field({field: None}, field) == ""

    @pytest.mark.parametrize("field", ["kind", "target_id", "rationale"])
    def test_an_absent_key_reads_as_empty(self, field):
        assert text_field({}, field) == ""

    def test_a_real_value_is_untouched(self):
        assert text_field({"kind": "stop"}, "kind") == "stop"

    @pytest.mark.parametrize("value,expected", [
        (0, "0"), (False, "False"), (0.0, "0.0"), ("", ""), (42, "42"),
    ])
    def test_falsy_but_present_values_are_not_swallowed(self, value, expected):
        """The reason this is `is None` and not `or ""`."""
        assert text_field({"v": value}, "v") == expected

    def test_the_result_is_always_a_string(self):
        for value in (None, 0, False, [], {"a": 1}, 3.5):
            assert isinstance(text_field({"v": value}, "v"), str)


class TestNullKind:
    """`{"kind": null}` was already rejected — but for a fabricated reason."""

    def test_a_null_kind_is_still_rejected(self):
        """The outcome must not change. Only the explanation does."""
        with pytest.raises(Rejected):
            make().validate({"kind": None, "target_id": "c1"})

    def test_a_null_kind_says_none_was_given_not_that_none_is_disallowed(self):
        with pytest.raises(Rejected) as exc:
            make().validate({"kind": None, "target_id": "c1"})
        assert "no action kind was given" in exc.value.reason

    @pytest.mark.parametrize("kind", [None, "", "   "])
    def test_no_absent_kind_is_ever_quoted_back_as_a_named_action(self, kind):
        """'none' is not something the model proposed; it must not read as if
        it were. Neither may a blank string masquerade as an action name."""
        with pytest.raises(Rejected) as exc:
            make().validate({"kind": kind, "target_id": "c1"})
        assert "'none'" not in exc.value.reason.lower()

    def test_a_real_unknown_kind_is_still_named_in_the_reason(self):
        """The honest message for a missing kind must not cost us the useful
        one for a kind that was actually proposed."""
        with pytest.raises(Rejected) as exc:
            make().validate({"kind": "set_bid", "target_id": "c1"})
        assert "'set_bid'" in exc.value.reason

    def test_the_permanent_ban_is_still_checked_first(self):
        with pytest.raises(Rejected, match="permanently forbidden"):
            make().validate({"kind": "start", "target_id": "c1"})

    def test_kind_is_still_stripped_and_lowercased(self):
        assert make().validate({"kind": "  STOP ", "target_id": "c1"}).kind == "stop"


class TestNullTargetId:
    """The one site with a path to acting on the wrong entity."""

    def test_a_null_target_cannot_resolve_to_an_id_literally_named_none(self):
        """`str(None)` is "None". An offered id of "None" — a real column
        value in exported data — would match it, and a proposal that named no
        target would execute against a real one."""
        guard = make(offered_ids=("None", "c1"))
        with pytest.raises(Rejected, match="was not offered"):
            guard.validate({"kind": "stop", "target_id": None})

    def test_a_null_target_is_quoted_as_empty_not_as_none(self):
        with pytest.raises(Rejected) as exc:
            make().validate({"kind": "stop", "target_id": None})
        assert "''" in exc.value.reason and "'None'" not in exc.value.reason

    def test_a_target_named_none_still_works_when_actually_proposed(self):
        """Rejecting null must not make the string "None" undecidable."""
        guard = make(offered_ids=("None", "c1"))
        action = guard.validate({"kind": "stop", "target_id": "None"})
        assert action.target_id == "None"

    def test_target_is_still_stripped_but_not_lowercased(self):
        guard = make(offered_ids=("C1",))
        assert guard.validate({"kind": "stop", "target_id": " C1 "}).target_id == "C1"


class TestNullCellsInTheEvidenceTable:
    """The table is handed to the model as the complete set of figures."""

    def test_a_null_cell_renders_as_an_empty_cell(self):
        block = Evidence([{"id": "a1", "spend": None}]).prompt_block()
        assert "None" not in block
        assert "a1 | " in block

    def test_a_null_cell_in_one_row_does_not_affect_the_others(self):
        block = Evidence([{"id": "a1", "spend": None},
                          {"id": "a2", "spend": 1_800.0}]).prompt_block()
        assert "None" not in block and "1800.0" in block

    def test_a_column_missing_from_a_row_still_renders_empty(self):
        """The pre-existing correct case, kept so the helper cannot regress it."""
        block = Evidence([{"id": "a1", "spend": 10.0},
                          {"id": "a2"}]).prompt_block()
        assert "None" not in block and "a2 | " in block

    def test_a_zero_cell_is_still_printed(self):
        """0 is a figure, not an absence — `or ""` would have erased it."""
        block = Evidence([{"id": "a1", "conversions": 0}]).prompt_block()
        assert "a1 | 0" in block

    def test_a_false_cell_is_still_printed(self):
        block = Evidence([{"id": "a1", "active": False}]).prompt_block()
        assert "a1 | False" in block

    def test_every_column_still_gets_a_cell(self):
        """Rendering must stay positional; a dropped null would shift the row."""
        block = Evidence([{"id": "a1", "spend": None, "clicks": 320}]).prompt_block()
        row = [line for line in block.splitlines() if line.startswith("a1")][0]
        assert row.split(" | ") == ["a1", "", "320"]


class TestRationaleStaysFixed:
    """#2's fix, now expressed through the shared helper."""

    def test_a_null_rationale_is_still_empty(self):
        action = make().validate(
            {"kind": "stop", "target_id": "c1", "rationale": None})
        assert action.rationale == ""

    def test_a_falsy_rationale_is_still_kept(self):
        action = make().validate(
            {"kind": "stop", "target_id": "c1", "rationale": 0})
        assert action.rationale == "0"

    def test_the_500_character_cap_survives_the_refactor(self):
        action = make().validate(
            {"kind": "stop", "target_id": "c1", "rationale": "x" * 900})
        assert len(action.rationale) == 500
