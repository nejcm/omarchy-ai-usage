"""Claude transcript parser tests; fixture lines are redacted, no real logs."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from support import FIXTURES  # noqa: E402

import usage_claude  # noqa: E402
import usage_scan  # noqa: E402

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def stream(output, thinking=None, message="msg-1", request="req-1"):
    usage = {"input_tokens": 1, "output_tokens": output}
    if thinking is not None:
        usage["output_tokens_details"] = {"thinking_tokens": thinking}
    return json.dumps({"type": "assistant", "timestamp": "2026-10-01T10:00:00.000Z", "sessionId": "s",
                       "requestId": request,
                       "message": {"id": message, "model": "claude-opus-5-5", "usage": usage}}) + "\n"


def parse(text, state=None):
    return usage_claude.parse(text, state or {}, 0)


class ClaudeCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.env = {"XDG_CACHE_HOME": str(self.home / "cache")}
        self.connection = usage_scan.open_database(usage_scan.database_path(str(self.home), self.env))
        self.addCleanup(self.connection.close)

    def transcript(self, name, text):
        path = self.home / ".claude" / "projects" / "session" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        os.utime(path, (NOW, NOW))
        return path

    def install(self):
        path = self.home / ".claude" / "projects" / "session" / "transcript.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((FIXTURES / "claude_usage.jsonl").read_bytes())
        os.utime(path, (NOW, NOW))

    def scan(self):
        return usage_scan.scan(self.connection, [usage_claude.source(str(self.home), self.env)], now=NOW)

    def rows(self):
        return self.connection.execute(
            "SELECT key, provider, ts, session, model, input, cache_read, cache_write, output, reasoning"
            " FROM events ORDER BY key").fetchall()


class ParserTests(unittest.TestCase):
    def test_usage_substring_prefilter_skips_decoding(self):
        original = json.loads
        with mock.patch.object(usage_claude.json, "loads", side_effect=original) as loads:
            self.assertEqual(parse(b'{"type":"user","message":{"content":"redacted"}}\n', {}), [])
            self.assertEqual(loads.call_count, 0)
            self.assertEqual(parse(b'{"type":"assistant","usage":{}}\n', {}), [])
            self.assertEqual(loads.call_count, 1)

    def test_malformed_and_unknown_lines_are_skipped(self):
        self.assertEqual(parse(b'{"usage": truncated\n', {}), [])
        self.assertEqual(parse(b'{"type":"user","usage":{}}\n', {}), [])
        self.assertEqual(parse(b'{"type":"assistant","message":"usage"}\n', {}), [])
        self.assertEqual(parse(b'{"type":"assistant","usage":{"input_tokens":1}}\n', {}), [])
        self.assertEqual(
            parse(b'{"type":"assistant","timestamp":"nope","message":{"id":"m","model":"x","usage":{}}}\n', {}), [])

    def test_invalid_metadata_and_counts_are_skipped(self):
        def line(session="s", model="x", request="r", usage=None):
            return json.dumps({"type": "assistant", "timestamp": "2026-10-01T10:00:00.000Z", "sessionId": session,
                               "requestId": request, "message": {"id": "m", "model": model, "usage": usage or {}}})

        for text in (line(session={"a": 1}), line(session=[]), line(model=[]), line(request=7),
                     line(usage={"input_tokens": -1}), line(usage={"output_tokens": 2 ** 63}),
                     line(usage={"output_tokens": 1e20}), line(usage={"cache_read_input_tokens": "5"}),
                     line(usage={"output_tokens": 1, "output_tokens_details": {"thinking_tokens": -3}})):
            with self.subTest(text=text):
                self.assertEqual(parse(text.encode() + b"\n", {}), [])

    def test_valid_record_with_fractional_count_is_skipped(self):
        record = {"type": "assistant", "timestamp": "2026-10-01T10:00:00.000Z", "sessionId": "s", "requestId": "r",
                  "message": {"id": "m", "model": "x", "usage": {"input_tokens": 1.5, "output_tokens": 1}}}
        self.assertEqual(parse((json.dumps(record) + "\n").encode(), {}), [])


class FixtureTests(ClaudeCase):
    def test_fixture_events(self):
        self.install()
        self.assertGreater(self.scan().read, 0)
        rows = self.rows()
        self.assertEqual([row[0] for row in rows],
                         ["claude:msg-1:req-1", "claude:msg-3:req-3", "claude:msg-4:req-4"])
        self.assertEqual(rows[0][1:5], ("claude", at("2026-10-01T10:00:00Z"), "session-1", "claude-opus-5-5"))
        self.assertEqual(rows[0][5:], (100, 200, 50, 90, 0))
        self.assertEqual(rows[1][4:], ("claude-opus-5-5", 10, 0, 0, 70, 30))
        self.assertEqual(rows[2][4:], ("claude-haiku-4-5", 5, 7, 0, 6, 0))

    def test_max_output_survives_later_writes(self):
        path = self.transcript("a.jsonl", stream(40))
        self.scan()
        with path.open("a") as handle:
            handle.write(stream(90))
        self.scan()
        with path.open("a") as handle:
            handle.write(stream(80))
        self.scan()
        self.assertEqual([(row[0], row[8]) for row in self.rows()], [("claude:msg-1:req-1", 90)])

    def test_growing_reasoning_keeps_the_greatest_total(self):
        path = self.transcript("a.jsonl", stream(40, thinking=10))
        self.scan()
        with path.open("a") as handle:
            handle.write(stream(100, thinking=30))
        self.scan()
        self.assertEqual([(row[8], row[9]) for row in self.rows()], [(70, 30)])

    def test_late_thinking_details_are_split_in(self):
        path = self.transcript("a.jsonl", stream(40))
        self.scan()
        with path.open("a") as handle:
            handle.write(stream(100, thinking=30))
        self.scan()
        self.assertEqual([(row[8], row[9]) for row in self.rows()], [(70, 30)])

    def test_equal_total_thinking_details_are_split_in(self):
        path = self.transcript("a.jsonl", stream(100))
        self.scan()
        with path.open("a") as handle:
            handle.write(stream(100, thinking=30))
        self.scan()
        with path.open("a") as handle:
            handle.write(stream(100))
        self.scan()
        self.assertEqual([(row[8], row[9]) for row in self.rows()], [(70, 30)])

    def test_smaller_replay_does_not_lower_totals(self):
        path = self.transcript("a.jsonl", stream(100, thinking=30))
        self.scan()
        with path.open("a") as handle:
            handle.write(stream(40, thinking=10))
        self.scan()
        self.assertEqual([(row[8], row[9]) for row in self.rows()], [(70, 30)])

    def test_invalid_values_are_skipped_and_scanning_progresses(self):
        invalid = json.dumps({"type": "assistant", "timestamp": "2026-10-01T10:00:01.000Z",
                              "sessionId": {"a": 1}, "requestId": "req-2",
                              "message": {"id": "msg-2", "model": "claude-opus-5-5",
                                          "usage": {"input_tokens": 1, "output_tokens": 1}}})
        overflowing = json.dumps({"type": "assistant", "timestamp": "2026-10-01T10:00:02.000Z",
                                  "sessionId": "s", "requestId": "req-3",
                                  "message": {"id": "msg-3", "model": "claude-opus-5-5",
                                              "usage": {"input_tokens": 1e20, "output_tokens": 1}}})
        path = self.transcript("a.jsonl", stream(40) + invalid + "\n" + overflowing + "\n" + stream(50, request="req-4"))
        self.assertGreater(self.scan().read, 0)
        self.assertEqual([row[0] for row in self.rows()], ["claude:msg-1:req-1", "claude:msg-1:req-4"])
        self.assertEqual(self.scan().read, 0)
        self.assertEqual(self.connection.execute("SELECT offset FROM files").fetchone()[0], path.stat().st_size)

    def test_global_key_deduplicates_across_files(self):
        self.transcript("a.jsonl", stream(90))
        self.transcript("b.jsonl", stream(40))
        self.scan()
        self.assertEqual([(row[0], row[8]) for row in self.rows()], [("claude:msg-1:req-1", 90)])


class SourceTests(unittest.TestCase):
    def test_source_follows_config_dir(self):
        default = usage_claude.source("/home/x", {})
        self.assertEqual(default.id, "claude")
        self.assertEqual(default.patterns, ("/home/x/.claude/projects/**/*.jsonl",))
        custom = usage_claude.source("/home/x", {"CLAUDE_CONFIG_DIR": "/custom"})
        self.assertEqual(custom.patterns, ("/custom/projects/**/*.jsonl",))


if __name__ == "__main__":
    unittest.main()
