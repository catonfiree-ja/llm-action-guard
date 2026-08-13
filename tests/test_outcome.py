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
