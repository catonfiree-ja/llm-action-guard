"""Let the model write the sentence. Never let it do the arithmetic.

A model asked to both analyse and explain will happily produce a number that
reads as if it came from your data and did not. Nothing downstream can catch
it, because a wrong figure and a right figure are the same shape. In a report
about spending, that is the most expensive failure available: it is confident,
specific, and invisible.

The split used here:

    code   ->  computes every figure, hands over a fixed table
    model  ->  orders, selects and phrases; may cite only what it was handed

`Evidence` carries the table into the prompt, and `unsupported_numbers()`
checks the way back — any figure in the model's prose that is not in the table
(within a rounding tolerance) is flagged before a human ever reads it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import text_field

# Order matters: the space-grouped form is tried first, and a space only
# continues a number when followed by exactly three digits. A plain `\s` in the
# character class merged "for 320 clicks at 26" into one number — which then
# looked fabricated and made the checker cry wolf on honest prose.
_NUMBER = re.compile(
    r"(?<![\w.,])-?\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?(?![\w])"  # 1 250,50
    r"|(?<![\w.,])-?\d[\d,.]*\d(?![\w])"                            # 1,250.50
    r"|(?<![\w.,])-?\d(?![\w])"                                     # 7
)

# Dates are not quantities. Left in, "31/12/2026" reads as three fabricated
# numbers and every dated sentence fails grounding.
_DATE = re.compile(
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
)


def _to_float(token: str) -> float | None:
    """Parse a human-written number without guessing which mark is decimal.

    Two rules, in order:

    1. A lone separator followed by exactly three digits is a thousands mark.
       '8,412' and '1.250' are both 8412 and 1250 — this grouping is near
       universal, while a three-digit fraction almost never appears in prose.
    2. Otherwise the separator that appears last is the decimal point, so
       '1,250.50' (Thai/US) and '1.250,50' (German) both give 1250.50.

    Getting this backwards is a 100-1000x error, so the rule is written down
    rather than inherited from whatever locale the process happens to run in.
    """
    t = token.strip().replace(" ", "").replace(" ", "")
    if not t or not any(c.isdigit() for c in t):
        return None
    neg = t.startswith("-")
    t = t.lstrip("-")

    seps = [i for i, c in enumerate(t) if c in ".,"]
    if not seps:
        body, frac = t, ""
    elif len(seps) == 1 and len(t) - seps[0] - 1 == 3:
        body, frac = t, ""                      # rule 1: thousands grouping
    else:
        cut = seps[-1]                          # rule 2: last one is decimal
        body, frac = t[:cut], t[cut + 1:]
        if not frac.isdigit() or len(frac) > 6:
            body, frac = t, ""

    body = re.sub(r"[.,]", "", body)
    if not body.isdigit():
        return None
    try:
        value = float(f"{body}.{frac}") if frac else float(body)
    except (ValueError, OverflowError):
        return None
    return -value if neg else value


def numbers_in(text: str) -> list[float]:
    """Every number a reader would see, ignoring dates, times and identifiers."""
    masked = _DATE.sub(lambda m: " " * len(m.group(0)), text or "")
    out = []
    for m in _NUMBER.finditer(masked):
        v = _to_float(m.group(0))
        if v is not None:
            out.append(v)
    return out


@dataclass
class Evidence:
    """The complete set of figures the model is permitted to cite.

    >>> ev = Evidence([{"id": "c1", "cost_per_click": 30.0, "clicks": 194}])
    >>> ev.unsupported_numbers("c1 costs 30 per click")
    []
    >>> ev.unsupported_numbers("c1 costs 3 per click")
    [3.0]
    """

    rows: list[dict]
    notes: dict = field(default_factory=dict)
    tolerance: float = 0.005          # 0.5% — rounding is fine, invention is not
    allow_counts_up_to: int | None = None
    """How large a bare integer may be and still count as counting.

    Defaults to `min(len(rows), 20)`. Without a ceiling the exemption grows
    with the table, so a 500-row report would wave through every integer under
    500 — the check would quietly stop checking exactly when there is most to
    get wrong.
    """

    def _count_ceiling(self) -> int:
        if self.allow_counts_up_to is not None:
            return max(0, self.allow_counts_up_to)
        return min(len(self.rows), 20)

    def values(self) -> set[float]:
        vals: set[float] = set()
        def add(v):
            if isinstance(v, bool):
                return
            if isinstance(v, (int, float)):
                vals.add(float(v))
            elif isinstance(v, str):
                # A JSON API that returns "4200.0" as a string would otherwise
                # make every true figure in the report look fabricated.
                f = _to_float(v)
                if f is not None:
                    vals.add(f)
        for row in self.rows:
            for v in row.values():
                add(v)
        for v in self.notes.values():
            add(v)
        return vals

    def supports(self, n: float) -> bool:
        # Counting what you were given is legitimate: "3 of the 5 campaigns".
        if float(n).is_integer() and 0 <= n <= self._count_ceiling():
            return True
        for known in self.values():
            if abs(n - known) <= max(abs(known), 1.0) * self.tolerance:
                return True
        return False

    def unsupported_numbers(self, text: str) -> list[float]:
        """Figures in `text` that did not come from this table."""
        return [n for n in numbers_in(text) if not self.supports(n)]

    def assert_grounded(self, text: str) -> None:
        bad = self.unsupported_numbers(text)
        if bad:
            raise ValueError(
                "model produced figures that are not in the evidence: "
                + ", ".join(f"{b:g}" for b in bad))

    def prompt_block(self) -> str:
        """The table plus the one instruction that matters, ready to embed."""
        if not self.rows:
            body_lines, cols = [], []
        else:
            cols = list(dict.fromkeys(k for r in self.rows for k in r))
            # A null cell is an absence, and must render as one. Left as
            # `str(...)` it prints "None" inside the table the model is told
            # to treat as the complete set of figures — a token it can read
            # back as data.
            body_lines = [" | ".join(text_field(r, c) for c in cols)
                          for r in self.rows]
        parts = [
            "Here is the complete set of figures. Use only these.",
            "Do not calculate, estimate, combine or round into new numbers.",
            "If a figure you want is not in this table, say so in words instead.",
            "",
        ]
        if cols:
            parts += [" | ".join(cols),
                      "-|-".join("-" * len(c) for c in cols),
                      *body_lines]
        else:
            parts.append("(no rows)")
        if self.notes:
            parts += ["", "Context: " + ", ".join(
                f"{k}={v}" for k, v in self.notes.items())]
        return "\n".join(parts)
