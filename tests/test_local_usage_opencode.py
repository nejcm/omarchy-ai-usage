"""OpenCode SQLite source tests; a temp db stands in for opencode.db."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from support import FIXTURES  # noqa: E402

import local_usage.claude  # noqa: E402
import local_usage.opencode  # noqa: E402
import local_usage.scan  # noqa: E402

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()
SCHEMA = """
CREATE TABLE message(
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL, data TEXT NOT NULL
)
"""


def message(message_id, created=NOW, updated=None, session="ses-1", role="assistant",
            model="deepseek-v4.1-flash", tokens=None):
    data = {"role": role, "tokens": tokens or {"input": 10, "output": 20, "reasoning": 5,
                                               "cache": {"read": 30, "write": 2}}}
    if model is not None:
        data["modelID"] = model
    return {"id": message_id, "session_id": session, "time_created": int(created * 1000),
            "time_updated": int((updated or created) * 1000), "data": json.dumps(data)}


class OpenCodeCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.env = {"XDG_CACHE_HOME": str(self.home / "cache"),
                    "OPENCODE_DATA_DIR": str(self.home / "opencode")}
        self.connection = local_usage.scan.open_database(local_usage.scan.database_path(str(self.home), self.env))
        self.addCleanup(self.connection.close)
        self.path = Path(local_usage.opencode.database_path(str(self.home), self.env))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.source = sqlite3.connect(str(self.path))
        self.addCleanup(self.source.close)
        self.source.execute(SCHEMA)

    def add(self, record):
        self.source.execute("INSERT OR REPLACE INTO message VALUES(?,?,?,?,?)",
                            (record["id"], record["session_id"], record["time_created"],
                             record["time_updated"], record["data"]))
        self.source.commit()

    def add_raw(self, message_id, data, created=NOW, session="ses-1"):
        stamp = int(created * 1000) if isinstance(created, (int, float)) and math.isfinite(created) else created
        self.add({"id": message_id, "session_id": session, "time_created": stamp,
                  "time_updated": stamp, "data": json.dumps(data)})

    def add_text(self, message_id, text, created=NOW, session="ses-1"):
        stamp = int(created * 1000)
        self.source.execute("INSERT OR REPLACE INTO message VALUES(?,?,?,?,?)",
                            (message_id, session, stamp, stamp, text))
        self.source.commit()

    def scan(self):
        return local_usage.scan.scan(self.connection, [local_usage.opencode.query(str(self.home), self.env)], now=NOW)

    def rows(self):
        return self.connection.execute(
            "SELECT key, provider, ts, session, model, input, cache_read, cache_write, output, reasoning"
            " FROM events ORDER BY key").fetchall()


class SourceTests(OpenCodeCase):
    def test_assistant_rows_in_window_are_indexed(self):
        self.add(message("msg-1"))
        self.add(message("msg-2", role="user", model=None))
        self.add(message("msg-3", created=NOW - 40 * 86400))
        self.scan()
        rows = self.rows()
        self.assertEqual([row[0] for row in rows], ["opencode:msg-1"])
        self.assertEqual(rows[0][1:5], ("opencode", NOW, "ses-1", "deepseek-v4.1-flash"))
        self.assertEqual(rows[0][5:], (10, 30, 2, 20, 5))

    def test_current_assistant_rows_are_indexed_alongside_legacy_rows(self):
        self.add(message("msg-old"))
        self.add(message("msg-new"))
        self.source.execute("CREATE TABLE session_message(id TEXT PRIMARY KEY, session_id TEXT,"
                            " type TEXT, time_created INTEGER, data TEXT)")
        tokens = {"input": 7, "output": 8, "reasoning": 1, "cache": {"read": 9, "write": 2}}
        self.source.execute("INSERT INTO session_message VALUES(?,?,?,?,?)", (
            "msg-new", "ses-new", "assistant", int(NOW * 1000),
            json.dumps({"model": {"id": "deepseek-v4.1-flash", "providerID": "opencode-go"},
                        "tokens": tokens})))
        self.source.execute("INSERT INTO session_message VALUES(?,?,?,?,?)", (
            "msg-user", "ses-new", "user", int(NOW * 1000), json.dumps({"tokens": tokens})))
        self.source.commit()
        self.scan()
        rows = self.rows()
        self.assertEqual([row[0] for row in rows], ["opencode:msg-new", "opencode:msg-old"])
        self.assertEqual(rows[0][1:5], ("opencode", NOW, "ses-new", "deepseek-v4.1-flash"))
        self.assertEqual(rows[0][5:], (7, 9, 2, 8, 1))

    def test_incompatible_current_table_does_not_hide_legacy_rows(self):
        self.add(message("msg-old"))
        self.source.execute("CREATE TABLE session_message(id TEXT PRIMARY KEY)")
        self.source.commit()
        self.scan()
        self.assertEqual([row[0] for row in self.rows()], ["opencode:msg-old"])

    def test_updated_tokens_replace_on_rescan(self):
        self.add(message("msg-1"))
        self.scan()
        self.assertEqual(self.rows()[0][5:], (10, 30, 2, 20, 5))
        updated = {"input": 11, "output": 99, "reasoning": 7, "cache": {"read": 31, "write": 0}}
        self.add(message("msg-1", updated=NOW + 60, tokens=updated))
        self.scan()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][5:], (11, 31, 0, 99, 7))

    def test_missing_database_is_absent(self):
        self.path.unlink()
        self.assertEqual(self.scan().read, 0)
        self.assertEqual(self.rows(), [])

    def test_invalid_rows_are_skipped(self):
        good = {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        self.add_raw("msg-model", {"role": "assistant", "modelID": 5, "tokens": good})
        self.add_raw("msg-time", {"role": "assistant", "modelID": "m", "tokens": good}, created="abc")
        self.add_raw("msg-inf", {"role": "assistant", "modelID": "m", "tokens": good}, created=float("inf"))
        self.add_raw("msg-negative", {"role": "assistant", "modelID": "m",
                                      "tokens": {"input": -1, "output": 1, "reasoning": 0,
                                                 "cache": {"read": 0, "write": 0}}})
        self.add_raw("msg-missing", {"role": "assistant", "modelID": "m", "tokens": {"output": 1}})
        self.add_raw("msg-huge", {"role": "assistant", "modelID": "m",
                                  "tokens": {"input": 2 ** 63, "output": 1, "reasoning": 0,
                                             "cache": {"read": 0, "write": 0}}})
        self.scan()
        self.assertEqual(self.rows(), [])

    def test_malformed_json_does_not_block_other_rows(self):
        self.add(message("msg-1"))
        self.add_text("msg-bad", "{not json")
        self.scan()
        self.assertEqual([row[0] for row in self.rows()], ["opencode:msg-1"])

    def test_boolean_token_fields_are_skipped(self):
        self.add_raw("msg-bool-input", {"role": "assistant", "modelID": "m",
                                        "tokens": {"input": True, "output": 1, "reasoning": 0,
                                                   "cache": {"read": 0, "write": 0}}})
        self.add_raw("msg-bool-read", {"role": "assistant", "modelID": "m",
                                       "tokens": {"input": 1, "output": 1, "reasoning": 0,
                                                  "cache": {"read": False, "write": 0}}})
        self.scan()
        self.assertEqual(self.rows(), [])

    def test_integral_real_counts_are_kept(self):
        real = {"input": 10.0, "output": 20.0, "reasoning": 5.0, "cache": {"read": 30.0, "write": 2.0}}
        self.add_raw("msg-real", {"role": "assistant", "modelID": "m", "tokens": real})
        self.add_raw("msg-fraction", {"role": "assistant", "modelID": "m",
                                      "tokens": {**real, "input": 10.5}})
        self.scan()
        rows = self.rows()
        self.assertEqual([row[0] for row in rows], ["opencode:msg-real"])
        self.assertEqual(rows[0][5:], (10, 30, 2, 20, 5))

    def test_relative_data_directory(self):
        current = os.getcwd()
        self.addCleanup(os.chdir, current)
        os.chdir(self.home)
        env = {"XDG_CACHE_HOME": str(self.home / "cache"), "OPENCODE_DATA_DIR": "relative"}
        path = self.home / "relative" / "opencode.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = message("msg-1")
        source = sqlite3.connect(str(path))
        source.execute(SCHEMA)
        source.execute("INSERT OR REPLACE INTO message VALUES(?,?,?,?,?)",
                       (record["id"], record["session_id"], record["time_created"],
                        record["time_updated"], record["data"]))
        source.commit()
        source.close()
        local_usage.scan.scan(self.connection, [local_usage.opencode.query(str(self.home), env)], now=NOW)
        self.assertEqual([row[0] for row in self.rows()], ["opencode:msg-1"])

    def test_file_and_query_sources_run_together(self):
        fixture = self.home / ".claude" / "projects" / "session" / "transcript.jsonl"
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_bytes((FIXTURES / "claude_usage.jsonl").read_bytes())
        os.utime(fixture, (NOW, NOW))
        self.add(message("msg-1"))
        sources = [local_usage.claude.source(str(self.home), self.env), local_usage.opencode.query(str(self.home), self.env)]
        local_usage.scan.scan(self.connection, sources, now=NOW)
        providers = [row[0] for row in self.connection.execute("SELECT DISTINCT provider FROM events ORDER BY provider")]
        self.assertEqual(providers, ["claude", "opencode"])


if __name__ == "__main__":
    unittest.main()
