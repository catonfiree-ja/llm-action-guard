"""An append-only record of every decision, including the refused ones.

Two things learned the hard way sit in this file.

First: the log is the only place that answers "who changed the budget, and
why". If it lives on a filesystem that resets on deploy, it is not a log, it is
a rumour. `JsonlAudit` takes an explicit path and never assumes durability;
`storage_note()` reports what it can actually tell you rather than pretending
to detect it.

Second: rejected proposals must be written too. If only successful actions are
recorded, a model that spent a week proposing something forbidden looks exactly
like a model that proposed nothing.

Everything written here originates from an untrusted model, so entries are
size-capped and depth-capped on the way in.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_STR = 2_000
MAX_ITEMS = 200
MAX_DEPTH = 20


def _plain(obj: Any, depth: int = 0) -> Any:
    """Make a value JSON-safe without flattening structure or trusting size.

    An earlier version stringified anything that was not a primitive, which
    quietly turned a rejected proposal dict into `"{'kind': 'stop', ...}"` — it
    still *looked* fine in the log and could not be queried afterwards.
    """
    if depth > MAX_DEPTH:
        return "<nested>"
    if is_dataclass(obj) and not isinstance(obj, type):
        return _plain(asdict(obj), depth + 1)
    if isinstance(obj, dict):
        out = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= MAX_ITEMS:
                out["…"] = f"[{len(obj) - MAX_ITEMS} more keys]"
                break
            out[str(k)[:MAX_STR]] = _plain(v, depth + 1)
        return out
    if isinstance(obj, (list, tuple, set)):
        items = list(obj)
        cut = [_plain(v, depth + 1) for v in items[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            cut.append(f"[{len(items) - MAX_ITEMS} more items]")
        return cut
    if isinstance(obj, str):
        return obj if len(obj) <= MAX_STR else \
            obj[:MAX_STR] + f"…[truncated {len(obj) - MAX_STR} chars]"
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return str(obj)[:MAX_STR]


class JsonlAudit:
    """One JSON object per line, flushed on write, safe across threads."""

    def __init__(self, path: str | os.PathLike, max_lines: int = 20_000,
                 clock=lambda: datetime.now(timezone.utc)) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_lines = max_lines
        self._clock = clock
        self._lock = threading.Lock()
        self._lines: int | None = None      # counted once, then tracked

    def record(self, event: str, **fields: Any) -> dict:
        payload = {k: _plain(v) for k, v in fields.items()}
        # Reserved keys win, so a model-supplied "at" cannot rewrite history.
        payload.pop("at", None)
        payload.pop("event", None)
        entry = {"at": self._clock().isoformat(), "event": str(event)[:200],
                 **payload}
        # ensure_ascii keeps U+2028/U+2029 escaped — unescaped they are line
        # breaks to many JSONL readers and split one record into two bad ones.
        line = json.dumps(entry, ensure_ascii=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            if self._lines is None:
                self._lines = sum(1 for _ in self.path.open(encoding="utf-8"))
            else:
                self._lines += 1
            if self._lines > self.max_lines:
                self._trim_locked()
        return entry

    def accepted(self, action: Any) -> dict:
        return self.record("accepted", action=action)

    def rejected(self, reason: str, proposal: Any) -> dict:
        """A refusal is evidence too — never drop it."""
        return self.record("rejected", reason=reason, proposal=proposal)

    def read(self) -> list[dict]:
        """Read the whole log eagerly.

        Deliberately not a generator: a half-consumed generator holds the file
        open, and on Windows that makes the next trim fail with PermissionError.
        Audit logs are bounded, so the simpler contract is worth the memory.
        """
        if not self.path.exists():
            return []
        out: list[dict] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # A torn final line must not hide the whole history.
                    continue
        return out

    def _trim_locked(self) -> None:
        """Cap the file. A failure here must never take down the caller."""
        try:
            with self.path.open(encoding="utf-8") as fh:
                lines = fh.readlines()
            if len(lines) <= self.max_lines:
                self._lines = len(lines)
                return
            keep = lines[-self.max_lines:]
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    out.writelines(keep)
                os.replace(tmp, self.path)   # atomic: no half-written window
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            self._lines = len(keep)
        except OSError:
            # Windows refuses the replace while another handle is open. An
            # over-length log is a far smaller problem than a write that
            # raises into the decision path, so give up until next time.
            self._lines = None

    def storage_note(self) -> str:
        """What can honestly be said about durability, for a status page.

        There is no reliable way to detect an ephemeral container filesystem
        from inside it, so this reports the resolved path and whether the
        operator has asserted durability — it does not guess.
        """
        asserted = os.environ.get("AUDIT_DURABLE", "").lower() in ("1", "true", "yes")
        state = ("asserted by AUDIT_DURABLE" if asserted else
                 "NOT asserted — if this filesystem resets on deploy, "
                 "history is lost")
        return f"audit log at {self.path.resolve()}; durability {state}"
