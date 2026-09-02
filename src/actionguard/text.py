"""One coercion, in one place: read an untrusted field as text.

`dict.get(key, default)` returns the default only when the key is *absent*. A
model that emits `{"rationale": null}` sends the key *with* a null value, so
the default never fires, `str(None)` runs, and the literal word "None" lands
wherever the field was headed — an audit log, an error message, or a table of
figures the model is told to trust. Each of those reads like something the
model actually said.

The test is `is None` and not `or ""` on purpose. `or ""` would also erase a
`0` or a `False`, which are real (if odd) model output and must survive. Only
null is an absence.

Every place that turns a field of an untrusted mapping into text goes through
here, so there is one behaviour to reason about instead of four.
"""
from __future__ import annotations

from typing import Any, Mapping


def text_field(mapping: Mapping[str, Any], key: str) -> str:
    """The value at `key` as text, with absent and null both reading as "".

    >>> text_field({"rationale": "over budget"}, "rationale")
    'over budget'
    >>> text_field({"rationale": None}, "rationale")
    ''
    >>> text_field({}, "rationale")
    ''
    >>> text_field({"value": 0}, "value")        # falsy, but not absent
    '0'
    >>> text_field({"value": False}, "value")
    'False'
    """
    value = mapping.get(key)
    return "" if value is None else str(value)
