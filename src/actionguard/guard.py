"""The validation layer between a language model and anything that costs money.

Why this exists rather than a carefully worded prompt: a prompt is a request,
and a model is free to decline it. In practice three things happen often enough
to design around —

  1. it names an entity that does not exist (a plausible-looking id it invented)
  2. it proposes a number far outside anything reasonable
  3. it answers differently to the same question five minutes later

None of those are bugs in the model; they are properties of it. So the rule
here is that every constraint lives in code, and the model's output is treated
exactly like input from a stranger on the internet: parsed, checked, and
discarded when it does not fit.
"""
from __future__ import annotations

from .actions import Action, ActionSpec, FORBIDDEN_KINDS, Rejected
from .text import text_field


class ActionGuard:
    """Validates model proposals against a code-defined contract.

    >>> guard = ActionGuard([ActionSpec("stop")], offered_ids=["c1"])
    >>> guard.validate({"kind": "stop", "target_id": "c1"}).kind
    'stop'
    >>> guard.validate({"kind": "start", "target_id": "c1"})
    Traceback (most recent call last):
    actionguard.actions.Rejected: 'start' is permanently forbidden
    """

    def __init__(
        self,
        specs: list[ActionSpec],
        offered_ids: list[str],
        current_values: dict[str, float] | None = None,
    ) -> None:
        bad = {s.kind for s in specs} & FORBIDDEN_KINDS
        if bad:
            raise ValueError(
                f"cannot permit permanently forbidden action(s): {sorted(bad)}"
            )
        if not offered_ids:
            raise ValueError("offered_ids is empty — nothing can be decided, "
                             "and an empty allow-list must not read as 'allow all'")
        self._specs = {s.kind: s for s in specs}
        self._offered = frozenset(offered_ids)
        self._current = dict(current_values or {})

    @property
    def offered_ids(self) -> frozenset[str]:
        """Exactly the ids the model was shown. Nothing else is decidable."""
        return self._offered

    @property
    def allowed_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def validate(self, proposal: dict) -> Action:
        """Turn an untrusted dict into an `Action`, or raise `Rejected`."""
        if not isinstance(proposal, dict):
            raise Rejected("proposal is not an object", proposal)

        kind = text_field(proposal, "kind").strip().lower()
        target = text_field(proposal, "target_id").strip()

        # Order matters: the permanent ban is checked before the allow-list, so
        # a misconfigured allow-list still cannot let a forbidden kind through.
        if kind in FORBIDDEN_KINDS:
            raise Rejected(f"{kind!r} is permanently forbidden", proposal)
        if not kind:
            # Same rejection, honest reason. Saying "'none' is not an allowed
            # action" sends whoever reads the log looking for a kind the model
            # never sent.
            raise Rejected(
                "no action kind was given — an absent, null or blank 'kind' "
                "is not an allowed action "
                f"(allowed: {', '.join(self.allowed_kinds)})", proposal)
        if kind not in self._specs:
            raise Rejected(
                f"{kind!r} is not an allowed action "
                f"(allowed: {', '.join(self.allowed_kinds)})", proposal)
        if target not in self._offered:
            raise Rejected(
                f"target_id {target!r} was not offered — the model may only "
                f"choose among ids it was given", proposal)

        spec = self._specs[kind]
        value: float | None = None
        if spec.needs_value:
            raw = proposal.get("value")
            try:
                # OverflowError matters: JSON has no integer limit, so a model
                # can hand back a 400-digit number. Without it the exception
                # escapes validate_all and destroys the whole batch.
                value = float(raw)
            except (TypeError, ValueError, OverflowError):
                raise Rejected(
                    f"{kind!r} requires a numeric value, got {raw!r}", proposal)
            if value != value or value in (float("inf"), float("-inf")):
                raise Rejected("value must be a finite number", proposal)
            value = spec.clamp(value, self._current.get(target))

        # A present-but-null rationale must not land in the audit log as the
        # word "None" — a line that reads like a reason the model gave. An
        # empty rationale is honest; a fabricated one is not. See `text_field`.
        return Action(
            kind=kind,
            target_id=target,
            value=value,
            rationale=text_field(proposal, "rationale")[:500],
        )

    def validate_all(self, proposals: list[dict]) -> tuple[list[Action], list[Rejected]]:
        """Validate a batch. One bad proposal never discards the good ones."""
        if proposals is None:
            return [], []
        if not isinstance(proposals, (list, tuple)):
            # A bare string would otherwise iterate character by character and
            # emit one rejection per letter.
            return [], [Rejected("actions is not a list", proposals)]
        kept: list[Action] = []
        dropped: list[Rejected] = []
        seen: set[tuple[str, str]] = set()
        for p in proposals:
            try:
                action = self.validate(p)
            except Rejected as exc:
                dropped.append(exc)
                continue
            key = (action.kind, action.target_id)
            if key in seen:                     # models repeat themselves
                dropped.append(Rejected("duplicate proposal", p))
                continue
            seen.add(key)
            kept.append(action)
        return kept, dropped
