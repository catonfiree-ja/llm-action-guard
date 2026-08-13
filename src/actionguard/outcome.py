"""Three-state results, because "no data" and "I could not read the data" are
not the same thing.

The bug this prevents is subtle and expensive. A fetch fails, the helper
swallows the error and returns an empty list, and every layer above reports
"nothing to do" in perfectly calm language. In a system that adjusts spending,
"nothing to optimise" and "I am blind right now" must never render the same.

    >>> Outcome.empty().is_empty
    True
    >>> Outcome.unknown("timeout").is_empty
    False

An `Outcome` is truthy only when it actually carries data, so the usual
`if not result:` idiom cannot silently conflate the two states.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar

T = TypeVar("T")


class DataUnavailable(RuntimeError):
    """Raised when code asks for values that were never successfully read."""


@dataclass(frozen=True)
class Outcome(Generic[T]):
    """Either data, a confirmed absence of data, or an unreadable source."""

    items: tuple[T, ...] | None
    reason: str | None = None

    @classmethod
    def ok(cls, items: Sequence[T]) -> "Outcome[T]":
        if isinstance(items, (str, bytes)):
            # tuple("abc") == ('a','b','c') — a silent explosion into
            # characters that only surfaces far downstream.
            raise TypeError("ok() takes a sequence of items, not a string")
        return cls(tuple(items))

    @classmethod
    def empty(cls) -> "Outcome[T]":
        """The source answered, and the answer was 'nothing'."""
        return cls(())

    @classmethod
    def unknown(cls, reason: str) -> "Outcome[T]":
        """The source did not answer. We know nothing."""
        if not reason:
            raise ValueError("unknown() requires a reason — an unexplained "
                             "failure is how this bug comes back")
        return cls(None, reason)

    @property
    def is_known(self) -> bool:
        return self.items is not None

    @property
    def is_empty(self) -> bool:
        """True only when the source confirmed there is nothing."""
        return self.items is not None and len(self.items) == 0

    def unwrap(self) -> tuple[T, ...]:
        """Get the data, or refuse loudly. Never guesses."""
        if self.items is None:
            raise DataUnavailable(self.reason or "source unavailable")
        return self.items

    def unwrap_or(self, default: Sequence[T]) -> tuple[T, ...]:
        """Explicit opt-in to a fallback. Callers must type it out."""
        return self.items if self.items is not None else tuple(default)

    def __bool__(self) -> bool:
        return bool(self.items)

    def __len__(self) -> int:
        return len(self.unwrap())
