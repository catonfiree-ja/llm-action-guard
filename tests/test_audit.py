import json
import threading
from datetime import datetime, timezone

import pytest

from actionguard import Action, JsonlAudit


@pytest.fixture
def audit(tmp_path):
    return JsonlAudit(tmp_path / "log" / "audit.jsonl")


def test_creates_its_directory(tmp_path):
    JsonlAudit(tmp_path / "deep" / "nested" / "a.jsonl").record("x")
    assert (tmp_path / "deep" / "nested" / "a.jsonl").exists()


def test_accepted_actions_are_recorded(audit):
    audit.accepted(Action(kind="stop", target_id="c1", rationale="no clicks"))
    entry = next(iter(audit.read()))
    assert entry["event"] == "accepted"
    assert entry["action"]["target_id"] == "c1"


def test_refusals_are_recorded_too(audit):
    """Otherwise a week of forbidden proposals looks like a quiet week."""
    audit.rejected("target_id was not offered", {"kind": "stop",
                                                 "target_id": "ghost"})
    entry = next(iter(audit.read()))
    assert entry["event"] == "rejected"
    assert entry["proposal"]["target_id"] == "ghost"


def test_entries_are_timestamped(tmp_path):
    fixed = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    a = JsonlAudit(tmp_path / "a.jsonl", clock=lambda: fixed)
    assert a.record("x")["at"] == fixed.isoformat()


def test_thai_text_survives_the_round_trip(audit):
    audit.record("note", reason="หยุดเพราะไม่มีคลิกเลย")
    assert next(iter(audit.read()))["reason"] == "หยุดเพราะไม่มีคลิกเลย"


def test_a_torn_line_does_not_hide_the_history(audit):
    audit.record("first")
    with audit.path.open("a", encoding="utf-8") as fh:
        fh.write('{"at": "broken"\n')          # truncated write
    audit.record("third")
    events = [e["event"] for e in audit.read()]
    assert events == ["first", "third"]


def test_reading_a_missing_file_is_empty_not_an_error(tmp_path):
    assert list(JsonlAudit(tmp_path / "nope.jsonl").read()) == []


class TestTrimming:
    def test_keeps_the_most_recent_entries(self, tmp_path):
        a = JsonlAudit(tmp_path / "a.jsonl", max_lines=10)
        for i in range(25):
            a.record("e", i=i)
        entries = list(a.read())
        assert len(entries) == 10
        assert [e["i"] for e in entries] == list(range(15, 25))

    def test_trim_is_atomic_leaving_no_partial_file(self, tmp_path):
        a = JsonlAudit(tmp_path / "a.jsonl", max_lines=5)
        for i in range(20):
            a.record("e", i=i)
        raw = a.path.read_text(encoding="utf-8").splitlines()
        assert all(json.loads(line) for line in raw)   # every line parses


def test_concurrent_writers_lose_nothing(tmp_path):
    a = JsonlAudit(tmp_path / "a.jsonl", max_lines=10_000)

    def spam(n):
        for i in range(50):
            a.record("e", who=n, i=i)

    threads = [threading.Thread(target=spam, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(list(a.read())) == 400


def test_durability_is_reported_not_assumed(tmp_path, monkeypatch):
    """It cannot detect an ephemeral filesystem, so it must not pretend to."""
    a = JsonlAudit(tmp_path / "a.jsonl")
    monkeypatch.delenv("AUDIT_DURABLE", raising=False)
    assert "NOT asserted" in a.storage_note()
    monkeypatch.setenv("AUDIT_DURABLE", "true")
    assert "asserted by AUDIT_DURABLE" in a.storage_note()


def test_untrusted_text_cannot_set_the_log_size(tmp_path):
    """Everything logged here came from a model."""
    a = JsonlAudit(tmp_path / "a.jsonl")
    a.rejected("too long", {"rationale": "x" * 100_000})
    assert "truncated" in a.read()[0]["proposal"]["rationale"]


def test_a_model_field_cannot_overwrite_the_timestamp(tmp_path):
    """`proposal={"at": ...}` is model-controlled; the record's own `at` is not."""
    a = JsonlAudit(tmp_path / "a.jsonl")
    entry = a.record("note", at="1999-01-01", note="hi")
    assert not entry["at"].startswith("1999")
    assert entry["event"] == "note" and entry["note"] == "hi"


def test_deeply_nested_output_does_not_recurse_forever(tmp_path):
    a = JsonlAudit(tmp_path / "a.jsonl")
    deep: dict = {}
    cur = deep
    for _ in range(300):
        cur["n"] = {}
        cur = cur["n"]
    a.rejected("deep", deep)
    assert a.read()


def test_line_separators_do_not_split_a_record(tmp_path):
    """U+2028 is a line break to many JSONL readers."""
    a = JsonlAudit(tmp_path / "a.jsonl")
    a.record("note", text="before after")
    assert len(a.path.read_text(encoding="utf-8").strip().splitlines()) == 1
    assert a.read()[0]["text"] == "before after"
