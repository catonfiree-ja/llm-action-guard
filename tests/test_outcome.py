import pytest

from actionguard import DataUnavailable, Outcome


def test_ok_carries_data():
    o = Outcome.ok([1, 2, 3])
    assert o.is_known and not o.is_empty and o.unwrap() == (1, 2, 3)


def test_empty_means_the_source_answered_nothing():
    o = Outcome.empty()
    assert o.is_known and o.is_empty and o.unwrap() == ()


def test_unknown_is_not_empty():
    """The whole point: a failed read must never read as 'nothing to do'."""
    o = Outcome.unknown("HTTP 500 from upstream")
    assert not o.is_known
    assert not o.is_empty


def test_unknown_requires_a_reason():
    with pytest.raises(ValueError):
        Outcome.unknown("")


def test_unwrap_refuses_rather_than_guessing():
    with pytest.raises(DataUnavailable, match="timeout"):
        Outcome.unknown("timeout").unwrap()


def test_fallback_must_be_typed_out_explicitly():
    assert Outcome.unknown("down").unwrap_or([9]) == (9,)
    assert Outcome.empty().unwrap_or([9]) == ()


def test_len_refuses_on_unknown():
    assert len(Outcome.ok([1, 2])) == 2
    assert len(Outcome.empty()) == 0
    with pytest.raises(DataUnavailable):
        len(Outcome.unknown("down"))


@pytest.mark.parametrize("outcome", [Outcome.empty(), Outcome.unknown("down")])
def test_both_falsy_states_are_falsy_so_bool_alone_cannot_be_trusted(outcome):
    """`if not result:` treats them alike — which is why callers must ask
    `is_empty` before ever printing 'nothing to do'."""
    assert not outcome


def test_the_reporting_bug_this_prevents():
    def render(o: Outcome) -> str:
        if not o.is_known:
            return f"cannot read right now: {o.reason}"
        if o.is_empty:
            return "nothing needs attention"
        return f"{len(o)} items need attention"

    assert render(Outcome.unknown("rate limited")) == \
        "cannot read right now: rate limited"
    assert render(Outcome.empty()) == "nothing needs attention"
    assert render(Outcome.ok([1])) == "1 items need attention"


class TestEmptyAndNoneInput:
    """`None` is the state this type exists to keep separate from empty."""

    def test_ok_with_an_empty_sequence_is_a_confirmed_absence(self):
        for empty in ([], (), set()):
            o = Outcome.ok(empty)
            assert o.is_known and o.is_empty and o.unwrap() == ()

    def test_ok_refuses_none_rather_than_inventing_an_empty_result(self):
        """`tuple(None)` would be a crash; silently returning () would be worse
        — a failed read must never render as 'nothing to do'."""
        with pytest.raises(TypeError):
            Outcome.ok(None)

    @pytest.mark.parametrize("text", ["", "abc"])
    def test_ok_refuses_a_string_including_an_empty_one(self, text):
        """tuple("abc") == ('a','b','c') — a silent explosion into characters."""
        with pytest.raises(TypeError, match="not a string"):
            Outcome.ok(text)

    @pytest.mark.parametrize("reason", ["", None])
    def test_unknown_refuses_a_blank_reason(self, reason):
        with pytest.raises(ValueError, match="requires a reason"):
            Outcome.unknown(reason)

    def test_a_reasonless_unknown_still_fails_loudly_if_one_is_built(self):
        """Constructed directly rather than through `unknown()`."""
        with pytest.raises(DataUnavailable, match="source unavailable"):
            Outcome(None, None).unwrap()

    def test_items_that_are_none_are_still_data(self):
        """A row of nulls is something the source said, not silence."""
        o = Outcome.ok([None, None])
        assert o.is_known and not o.is_empty and len(o) == 2 and bool(o)

    def test_an_empty_fallback_is_still_an_explicit_choice(self):
        assert Outcome.unknown("down").unwrap_or([]) == ()
        assert Outcome.unknown("down").unwrap_or(()) == ()

    def test_empty_and_unknown_are_never_equal(self):
        assert Outcome.empty() != Outcome.unknown("down")
