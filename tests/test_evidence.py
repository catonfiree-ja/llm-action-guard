import pytest

from actionguard import Evidence, numbers_in
from actionguard.evidence import _to_float

ROWS = [
    {"id": "a1", "cost_per_click": 12.5, "clicks": 320, "spend": 4_000.0},
    {"id": "a2", "cost_per_click": 2.0, "clicks": 900, "spend": 1_800.0},
]


@pytest.fixture
def ev():
    return Evidence(ROWS)


class TestNumberParsing:
    @pytest.mark.parametrize("text,expected", [
        ("1,250.50", 1_250.50),     # Thai / US
        ("1.250,50", 1_250.50),     # German
        ("1 250,50", 1_250.50),     # French
        ("30", 30.0),
        ("30.5", 30.5),
        ("-42", -42.0),
        ("8,412", 8_412.0),         # lone separator + 3 digits = thousands
        ("1.250", 1_250.0),         # same rule, other convention
        ("30.55", 30.55),           # 2 digits after = decimal
    ])
    def test_separator_rules(self, text, expected):
        assert _to_float(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text", ["a1", "v1.2.3", "GTM-XXXX000", "utm_1"])
    def test_digits_inside_identifiers_are_not_figures(self, text):
        """Otherwise every campaign id becomes a number the model 'cited'."""
        assert numbers_in(text) == []

    @pytest.mark.parametrize("junk", ["", "abc", "-", ".", ",", "  "])
    def test_non_numbers_return_none(self, junk):
        assert _to_float(junk) is None

    def test_finds_every_number_a_reader_would_see(self):
        found = numbers_in("a1 spent 8,412 for 320 clicks at 26 each")
        assert 8_412.0 in found and 320.0 in found and 26.0 in found


class TestGrounding:
    def test_quoted_figures_pass(self, ev):
        assert ev.unsupported_numbers("a1 cost 12.5 per click over 320 clicks") == []

    def test_invented_figure_is_caught(self, ev):
        """The failure this whole module exists for."""
        assert ev.unsupported_numbers("a1 cost 3 per click") == [3.0]

    def test_rounding_is_tolerated(self):
        e = Evidence([{"cpc": 29.97}])
        assert e.unsupported_numbers("about 30 per click") == []

    def test_a_number_far_from_any_evidence_is_flagged(self):
        e = Evidence([{"cpc": 29.97}])
        assert e.unsupported_numbers("about 45 per click") == [45.0]

    def test_counting_the_rows_is_allowed(self, ev):
        assert ev.unsupported_numbers("2 of the campaigns are wasteful") == []

    def test_counting_beyond_the_rows_is_not(self, ev):
        assert ev.unsupported_numbers("all 9 campaigns are wasteful") == [9.0]

    def test_assert_grounded_raises_with_the_offending_figure(self, ev):
        with pytest.raises(ValueError, match="3"):
            ev.assert_grounded("cost was 3 per click")

    def test_assert_grounded_is_silent_when_clean(self, ev):
        ev.assert_grounded("a1 had 320 clicks")

    def test_notes_are_citable(self):
        e = Evidence([], notes={"days": 30})
        assert e.unsupported_numbers("over the last 30 days") == []

    def test_booleans_are_not_treated_as_numbers(self):
        e = Evidence([{"active": True, "cpc": 30.0}])
        assert 1.0 not in e.values()


class TestPromptBlock:
    def test_carries_the_instruction_and_the_data(self, ev):
        block = ev.prompt_block()
        assert "Use only these" in block
        assert "Do not calculate" in block
        assert "4000" in block.replace(",", "") or "4000.0" in block

    def test_empty_evidence_is_explicit(self):
        block = Evidence([]).prompt_block()
        assert "(no rows)" in block and "Use only these" in block


class TestEmptyAndNoneInput:
    """Empty prose and an empty table are both normal. Neither may turn the
    grounding check into a formality that passes everything."""

    @pytest.mark.parametrize("text", ["", None, "   ", "no figures here"])
    def test_text_without_figures_has_nothing_to_check(self, ev, text):
        assert numbers_in(text) == []
        assert ev.unsupported_numbers(text) == []
        ev.assert_grounded(text)

    def test_an_empty_table_supports_no_figure(self):
        """The dangerous reading is 'nothing known, so nothing to object to'."""
        assert Evidence([]).unsupported_numbers("we spent 500") == [500.0]

    def test_an_empty_table_still_permits_counting_nothing(self):
        assert Evidence([]).unsupported_numbers("0 campaigns need attention") == []

    def test_empty_rows_contribute_no_values(self):
        assert Evidence([{}, {}]).values() == set()

    @pytest.mark.parametrize("cell", [None, "", "   ", "n/a"])
    def test_a_blank_cell_is_not_a_citable_figure(self, cell):
        """A null cost must not become a licence to write any number."""
        e = Evidence([{"id": "a1", "spend": cell}])
        assert e.values() == set()
        assert e.unsupported_numbers("a1 spent 4,000") == [4_000.0]

    def test_blank_notes_are_ignored(self):
        assert Evidence([], notes={"days": None, "window": ""}).values() == set()

    def test_a_zero_in_the_table_is_citable(self):
        """0.0 is a figure, not an absence — `if not value` would drop it."""
        e = Evidence([{"id": "a1", "conversions": 0}])
        assert 0.0 in e.values()

    def test_rows_of_empty_dicts_render_as_no_rows(self):
        block = Evidence([{}]).prompt_block()
        assert "(no rows)" in block and "Use only these" in block

    def test_an_empty_table_keeps_its_notes_in_the_prompt(self):
        block = Evidence([], notes={"days": 30}).prompt_block()
        assert "(no rows)" in block and "days=30" in block

    def test_the_count_exemption_shrinks_with_an_empty_table(self):
        """Otherwise a report over no data waves through every small integer."""
        assert Evidence([]).unsupported_numbers("3 of them are wasteful") == [3.0]

    def test_an_explicit_zero_ceiling_disables_the_count_exemption(self, ev):
        """Counting is a courtesy, and an operator may withdraw it."""
        assert ev.unsupported_numbers("1 campaign is wasteful") == []
        strict = Evidence(ROWS, allow_counts_up_to=0)
        assert strict.unsupported_numbers("1 campaign is wasteful") == [1.0]
