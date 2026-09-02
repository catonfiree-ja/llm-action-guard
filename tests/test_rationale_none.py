"""A null rationale must become an empty string, never the word "None".

`dict.get(key, default)` returns the default only when the key is *absent*.
A model that emits `{"rationale": null}` sends the key with a null value, so
the default never fires and `str(None)` puts the literal text "None" into the
audit log — a line that reads like a reason the model gave. An empty rationale
is honest about the absence; a fabricated one is worse than no log at all.
"""
from actionguard import ActionGuard, ActionSpec

SPECS = [
    ActionSpec("stop"),
    ActionSpec("set_budget", needs_value=True, min_value=50,
               max_value=100_000, max_change_ratio=0.20),
]


def make():
    return ActionGuard(SPECS, offered_ids=["c1", "c2"],
                       current_values={"c1": 1_000.0, "c2": 500.0})


def test_null_rationale_becomes_empty_not_the_string_none():
    action = make().validate(
        {"kind": "stop", "target_id": "c1", "rationale": None})
    assert action.rationale == ""


def test_null_rationale_never_renders_as_none_anywhere():
    """Guards the exact audit-log symptom, not just the equality above."""
    action = make().validate(
        {"kind": "stop", "target_id": "c1", "rationale": None})
    assert "None" not in action.rationale
    assert "none" not in action.rationale.lower()


def test_missing_rationale_key_still_becomes_empty():
    action = make().validate({"kind": "stop", "target_id": "c1"})
    assert action.rationale == ""


def test_null_rationale_on_a_valued_action_is_also_empty():
    """The value branch builds the same Action; it must not be a second path."""
    action = make().validate({"kind": "set_budget", "target_id": "c1",
                              "value": 1_100, "rationale": None})
    assert action.rationale == ""
    assert action.value == 1_100


def test_a_real_rationale_is_still_preserved():
    action = make().validate({"kind": "stop", "target_id": "c1",
                              "rationale": "no clicks in 14 days"})
    assert action.rationale == "no clicks in 14 days"


def test_non_string_rationale_is_still_coerced_to_text():
    """Only None is special-cased — other junk still becomes a string."""
    action = make().validate(
        {"kind": "stop", "target_id": "c1", "rationale": 42})
    assert action.rationale == "42"


def test_falsy_but_present_rationale_is_not_swallowed():
    """`or ""` would erase these; a null check must not."""
    zero = make().validate(
        {"kind": "stop", "target_id": "c1", "rationale": 0})
    assert zero.rationale == "0"

    false = make().validate(
        {"kind": "stop", "target_id": "c1", "rationale": False})
    assert false.rationale == "False"


def test_the_500_char_cap_still_applies():
    action = make().validate(
        {"kind": "stop", "target_id": "c1", "rationale": "x" * 900})
    assert action.rationale == "x" * 500
