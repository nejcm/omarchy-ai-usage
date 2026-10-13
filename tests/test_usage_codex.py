"""Codex rollout parser tests; fixture lines are redacted, no real logs."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from support import FIXTURES  # noqa: E402

import usage_codex  # noqa: E402
import usage_scan  # noqa: E402

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def fixture_lines(name):
    return (FIXTURES / name).read_bytes().splitlines(keepends=True)


def line_offsets(name):
    offsets, position = [], 0
    for piece in fixture_lines(name):
        offsets.append(position)
        position += len(piece)
    return offsets


def parse(record, state, offset=0):
    line = record if isinstance(record, bytes) else json.dumps(record).encode()
    return usage_codex.parse(line + b"\n", state, offset)


class CodexCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.env = {"XDG_CACHE_HOME": str(self.home / "cache")}
        self.connection = usage_scan.open_database(usage_scan.database_path(str(self.home), self.env))
        self.addCleanup(self.connection.close)

    def install(self, name, target="sessions/2026/10/01/session.jsonl"):
        path = self.home / ".codex" / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((FIXTURES / name).read_bytes())
        os.utime(path, (NOW, NOW))
        return path

    def scan(self):
        return usage_scan.scan(self.connection, [usage_codex.source(str(self.home), self.env)], now=NOW)

    def rows(self):
        return self.connection.execute(
            "SELECT key, provider, ts, session, model, input, cache_read, cache_write, output, reasoning"
            " FROM events ORDER BY ts, key").fetchall()

    def state(self, path):
        row = self.connection.execute("SELECT state FROM files WHERE path = ?", (str(path),)).fetchone()
        return json.loads(row[0])


class FixtureTests(CodexCase):
    def test_session_events_use_last_usage(self):
        path = self.install("codex_session.jsonl")
        self.assertGreater(self.scan(), 0)
        offsets = line_offsets("codex_session.jsonl")
        rows = self.rows()
        self.assertEqual([row[0] for row in rows],
                         ["codex:session-1:%d" % offsets[2], "codex:session-1:%d" % offsets[4]])
        self.assertEqual(rows[0][1:5], ("codex", at("2026-10-01T08:00:02Z"), "session-1", "gpt-6.1-sol"))
        self.assertEqual(rows[0][5:], (600, 400, 0, 60, 40))
        self.assertEqual(rows[1][5:], (300, 0, 0, 40, 10))
        state = self.state(path)
        self.assertEqual(state["session"], "session-1")
        self.assertEqual(state["model"], "gpt-6.1-sol")
        self.assertEqual(state["signature"], [300, 0, 0, 50, 10, 350, 1200, 300, 0, 150, 50, 1350])

    def test_repeated_notification_is_skipped_across_runs(self):
        path = self.install("codex_session.jsonl")
        self.scan()
        with path.open("ab") as handle:
            handle.write(fixture_lines("codex_session.jsonl")[4])
        self.assertGreater(self.scan(), 0)
        self.assertEqual(len(self.rows()), 2)

    def test_fork_ignores_replayed_history_and_keeps_child_id(self):
        self.install("codex_fork.jsonl")
        self.scan()
        offsets = line_offsets("codex_fork.jsonl")
        rows = self.rows()
        self.assertEqual([row[0] for row in rows], ["codex:child-1:%d" % offsets[4]])
        self.assertEqual(rows[0][2:5], (at("2026-10-01T09:00:05Z"), "child-1", "gpt-6.1-sol"))
        self.assertEqual(rows[0][5:], (500, 200, 0, 20, 10))

    def test_subagent_archive_is_counted(self):
        self.install("codex_subagent.jsonl", target="archived_sessions/session.jsonl")
        self.scan()
        offsets = line_offsets("codex_subagent.jsonl")
        rows = self.rows()
        self.assertEqual([row[0] for row in rows], ["codex:sub-1:%d" % offsets[2]])
        self.assertEqual(rows[0][5:], (150, 50, 0, 10, 0))


class ParserTests(unittest.TestCase):
    def usage(self, input_tokens=5, cached=0, cache_write=0, output=1, reasoning=0):
        entry = {"input_tokens": input_tokens, "cached_input_tokens": cached,
                 "cache_write_input_tokens": cache_write, "output_tokens": output,
                 "reasoning_output_tokens": reasoning, "total_tokens": 6}
        return {"type": "event_msg", "timestamp": "2026-10-01T08:00:00Z",
                "payload": {"type": "token_count", "info": {"last_token_usage": entry, "total_token_usage": entry}}}

    def header(self, **payload):
        return {"type": "session_meta", "timestamp": "2026-10-01T08:00:00Z", "payload": payload}

    def test_invalid_metadata_is_ignored(self):
        state = {"signature": [1]}
        parse({"type": "turn_context", "timestamp": "2026-10-01T08:00:00Z", "payload": {"model": 5}}, state)
        self.assertEqual(state, {"signature": [1]})
        parse(self.header(id="s1"), state)
        parse({"type": "turn_context", "timestamp": "2026-10-01T08:00:00Z", "payload": {"model": "m1"}}, state)
        self.assertEqual(state, {"signature": [1], "header": True, "session": "s1", "model": "m1"})

    def test_second_session_meta_does_not_replace_the_session(self):
        state = {}
        parse(self.header(id="child"), state)
        parse(self.header(id="parent"), state)
        self.assertEqual(state["session"], "child")

    def test_first_header_without_a_valid_id_is_never_replaced(self):
        state = {}
        parse(self.header(forked_from_id="parent"), state)
        parse(self.header(id="parent"), state)
        self.assertNotIn("session", state)
        self.assertEqual(parse(self.usage(), state), [])

    def test_fork_without_a_boundary_emits_nothing(self):
        for timestamp in (None, "nope"):
            with self.subTest(timestamp=timestamp):
                state = {}
                header = self.header(id="child", forked_from_id="parent")
                if timestamp is None:
                    header.pop("timestamp")
                else:
                    header["timestamp"] = timestamp
                parse(header, state)
                self.assertTrue(state["forked"])
                self.assertNotIn("fork_ts", state)
                self.assertEqual(parse(self.usage(), state), [])

    def test_token_count_requires_a_session_and_valid_counts(self):
        record = self.usage()
        self.assertEqual(parse(record, {}), [])
        self.assertEqual(parse({**record, "payload": {"type": "token_count", "info": None}}, {"session": "s"}), [])
        state = {"session": "s"}
        for value in (-1, 2 ** 63, 1e20, "5", 1.5, True):
            with self.subTest(value=value):
                self.assertEqual(parse(self.usage(input_tokens=value), state), [])
        self.assertEqual(state, {"session": "s"})
        events = parse(record, state)
        self.assertEqual(events[0]["key"], "codex:s:0")
        self.assertEqual(events[0]["input"], 5)
        self.assertEqual(state["signature"], [5, 0, 0, 1, 0, 6, 5, 0, 0, 1, 0, 6])

    def test_inconsistent_subset_counts_are_capped(self):
        events = parse(self.usage(input_tokens=100, cached=300, output=10, reasoning=20), {"session": "s"})
        self.assertEqual([events[0][name] for name in ("input", "cache_read", "output", "reasoning")],
                         [0, 100, 0, 10])

    def test_cache_write_change_is_not_a_duplicate(self):
        state = {"session": "s"}
        self.assertEqual(len(parse(self.usage(cache_write=0), state)), 1)
        self.assertEqual(len(parse(self.usage(cache_write=7), state)), 1)
        self.assertEqual(parse(self.usage(cache_write=7), state), [])

    def test_invalid_json_is_skipped(self):
        self.assertEqual(parse(b'{"token_count": truncated', {"session": "s"}), [])


class SourceTests(unittest.TestCase):
    def test_source_follows_codex_home(self):
        default = usage_codex.source("/home/x", {})
        self.assertEqual(default.id, "codex")
        self.assertEqual(default.patterns, ("/home/x/.codex/sessions/**/*.jsonl",
                                            "/home/x/.codex/archived_sessions/**/*.jsonl"))
        custom = usage_codex.source("/home/x", {"CODEX_HOME": "/custom"})
        self.assertEqual(custom.patterns, ("/custom/sessions/**/*.jsonl",
                                           "/custom/archived_sessions/**/*.jsonl"))


if __name__ == "__main__":
    unittest.main()
