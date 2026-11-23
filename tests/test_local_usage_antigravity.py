"""Antigravity conversation-database source tests; temp dbs mirror the agy CLI layout."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import support  # noqa: F401

import local_usage.antigravity  # noqa: E402
import local_usage.scan  # noqa: E402

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()
STARTED = int(NOW) - 600
SCHEMA = """
CREATE TABLE steps(idx INTEGER PRIMARY KEY, metadata BLOB);
CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE trajectory_metadata_blob(id TEXT PRIMARY KEY, data BLOB);
"""


def varint(value):
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint(number << 3 | 2) + varint(len(value)) + value


def timestamp(number, seconds):
    return field(number, field(1, seconds) + field(2, 123))


def generation(model="gemini-3.8-flash-n", step=None, **usage):
    numbers = {"model_enum": 1, "input": 2, "output": 3, "cache_write": 4, "cache_read": 5, "thinking": 9}
    stats = b"".join(field(numbers[name], value) for name, value in usage.items())
    labels = b"" if step is None else field(20, field(1, "last_step_index") + field(2, str(step)))
    body = field(4, stats) + field(6, 0x0102030405060708) + field(19, model) + labels
    return field(1, body) + field(4, "trace")


class AntigravityCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = str(Path(temporary.name))
        self.env = {"XDG_CACHE_HOME": os.path.join(self.home, "cache")}
        self.connection = local_usage.scan.open_database(local_usage.scan.database_path(self.home, self.env))
        self.addCleanup(self.connection.close)
        self.directory = Path(local_usage.antigravity.conversations_directory(self.home))
        self.directory.mkdir(parents=True)

    def conversation(self, name, generations, steps=None, started=STARTED):
        connection = sqlite3.connect(str(self.directory / ("%s.db" % name)))
        connection.executescript(SCHEMA)
        if started is not None:
            connection.execute("INSERT INTO trajectory_metadata_blob VALUES('main', ?)", (timestamp(2, started),))
        connection.executemany("INSERT INTO steps VALUES(?,?)",
                               [(index, timestamp(1, seconds)) for index, seconds in (steps or {}).items()])
        connection.executemany("INSERT INTO gen_metadata VALUES(?,?)", list(enumerate(generations)))
        connection.commit()
        connection.close()

    def scan(self):
        return local_usage.scan.scan(self.connection, [local_usage.antigravity.query(self.home, self.env)], now=NOW)

    def rows(self):
        return self.connection.execute(
            "SELECT key, provider, ts, session, model, input, cache_read, cache_write, output, reasoning"
            " FROM events ORDER BY key").fetchall()


class SourceTests(AntigravityCase):
    def test_generations_are_indexed_with_step_time(self):
        self.conversation("conv-1", [
            generation(step=0, model_enum=1320, input=13090, output=73),
            generation(step=2, model_enum=1320, input=2208, output=80, cache_read=11043),
            generation(step=4, input=12301, output=574, thinking=535, cache_write=7),
        ], steps={0: int(NOW) - 30, 2: int(NOW) - 20})
        self.scan()
        self.assertEqual(self.rows(), [
            ("antigravity:conv-1:0", "antigravity", NOW - 30, "conv-1", "gemini-3.8-flash-n", 13090, 0, 0, 73, 0),
            ("antigravity:conv-1:1", "antigravity", NOW - 20, "conv-1", "gemini-3.8-flash-n", 2208, 11043, 0, 80, 0),
            ("antigravity:conv-1:2", "antigravity", STARTED, "conv-1", "gemini-3.8-flash-n", 12301, 0, 7, 39, 535),
        ])

    def test_rescan_is_idempotent(self):
        self.conversation("conv-1", [generation(input=1, output=2)])
        self.scan()
        self.scan()
        self.assertEqual(len(self.rows()), 1)

    def test_malformed_and_untimed_generations_are_skipped(self):
        self.conversation("conv-1", [b"\xff\xff", b"", field(3, "config"), generation(input=5, output=1)])
        self.conversation("conv-2", [generation(input=1, output=1)], started=None)
        (self.directory / "conv-3.db").write_bytes(b"not a database")
        self.scan()
        self.assertEqual([row[0] for row in self.rows()], ["antigravity:conv-1:3"])

    def test_bad_model_or_count_skips_only_that_generation(self):
        self.conversation("conv-1", [generation(input=5, output=1), generation(model=7, input=1),
                                     generation(input=2 ** 63, output=1), generation(input=3, output=1)])
        self.scan()
        self.assertEqual([row[0] for row in self.rows()], ["antigravity:conv-1:0", "antigravity:conv-1:3"])

    def test_stale_conversations_are_skipped(self):
        self.conversation("conv-old", [generation(input=1, output=1)])
        old = NOW - 400 * 86400
        os.utime(self.directory / "conv-old.db", (old, old))
        self.scan()
        self.assertEqual(self.rows(), [])

    def test_missing_directory_is_absent(self):
        self.directory.rmdir()
        self.scan()
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
