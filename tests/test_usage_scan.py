"""Scanner state tests against temporary log files; no real logs are read."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import ROOT  # noqa: E402

import usage_scan  # noqa: E402

NOW = 1700000000.0


def event(key, ts=NOW, **fields):
    return json.dumps({"key": key, "ts": ts, **fields}) + "\n"


def stub_parse(line, state, offset):
    record = json.loads(line)
    state["lines"] = state.get("lines", 0) + 1
    return [{"key": record["key"], "ts": record["ts"], "session": record.get("session", ""),
             "model": record.get("model", "stub"), "input": record.get("input", 0),
             "cache_read": record.get("cache_read", 0), "cache_write": record.get("cache_write", 0),
             "output": record.get("output", 0), "reasoning": record.get("reasoning", 0)}]


class ScanCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.logs = self.home / "logs"
        self.logs.mkdir()
        self.connection = usage_scan.open_database(str(self.home / "cache" / "usage.db"))
        self.addCleanup(self.connection.close)
        self.sources = [self.source()]

    def source(self, parse=stub_parse, root=None):
        return usage_scan.Source("stub", (str((root or self.logs) / "**" / "*.jsonl"),), parse)

    def write(self, name, text):
        path = self.logs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def scan(self, now=NOW, budget=usage_scan.BUDGET_BYTES):
        return usage_scan.scan(self.connection, self.sources, now=now, budget=budget)

    def keys(self):
        return [row[0] for row in self.connection.execute("SELECT key FROM events ORDER BY key")]

    def events(self):
        return self.connection.execute(
            "SELECT key, ts, provider, session, model, input, cache_read, cache_write, output, reasoning"
            " FROM events ORDER BY key").fetchall()

    def files(self):
        return {row[0]: row for row in self.connection.execute(
            "SELECT path, inode, size, mtime_ns, offset, state FROM files")}

    def offset(self, path):
        return self.files()[str(path)][4]

    def state(self, path):
        return json.loads(self.files()[str(path)][5])


class StateTests(ScanCase):
    def test_cold_scan_indexes_complete_lines(self):
        path = self.write("nested/a.jsonl", event("k1", model="m1", input=7) + event("k2", cache_read=3))
        read = self.scan()
        self.assertEqual(read, path.stat().st_size)
        self.assertEqual(self.offset(path), path.stat().st_size)
        rows = self.events()
        self.assertEqual([row[0] for row in rows], ["k1", "k2"])
        self.assertEqual(rows[0][:5], ("k1", 1700000000.0, "stub", "", "m1"))
        self.assertEqual(rows[0][5], 7)
        self.assertEqual(rows[1][6], 3)

    def test_partial_trailing_line_waits(self):
        complete = event("k1")
        path = self.write("a.jsonl", complete + '{"key": "k2",')
        self.scan()
        self.assertEqual(self.keys(), ["k1"])
        self.assertEqual(self.offset(path), len(complete.encode()))
        with path.open("a") as handle:
            handle.write('"ts": 1700000001}\n')
        self.scan()
        self.assertEqual(self.keys(), ["k1", "k2"])
        self.assertEqual(self.offset(path), path.stat().st_size)

    def test_append_rescan_never_doubles(self):
        path = self.write("a.jsonl", event("k1"))
        self.scan()
        with path.open("a") as handle:
            handle.write(event("k2"))
        self.scan()
        self.assertEqual(self.scan(), 0)
        self.assertEqual(self.keys(), ["k1", "k2"])
        self.assertEqual(self.state(path), {"lines": 2})

    def test_budget_spreads_cold_scan_over_runs(self):
        texts = [event("k%d" % index) for index in range(4)]
        for index, text in enumerate(texts):
            self.write("%d.jsonl" % index, text)
        size = len(texts[0].encode())
        budget = 3 * size
        self.assertEqual(self.scan(budget=budget), budget)
        self.assertEqual(self.keys(), ["k0", "k1", "k2"])
        self.assertEqual(self.scan(budget=budget), size)
        self.assertEqual(self.keys(), ["k0", "k1", "k2", "k3"])
        self.assertEqual(self.scan(budget=budget), 0)

    def test_budget_resumes_mid_file(self):
        texts = [event("k0"), event("k1"), event("k2")]
        path = self.write("a.jsonl", "".join(texts))
        size = len(texts[0].encode())
        self.assertEqual(self.scan(budget=2 * size), 2 * size)
        self.assertEqual(self.keys(), ["k0", "k1"])
        self.assertEqual(self.offset(path), 2 * size)
        self.assertEqual(self.scan(budget=2 * size), size)
        self.assertEqual(self.keys(), ["k0", "k1", "k2"])
        self.assertEqual(self.offset(path), path.stat().st_size)
        self.assertEqual(self.state(path), {"lines": 3})

    def test_failed_file_consumes_budget(self):
        first = self.write("a.jsonl", event("k1") + event("boom", ts=1700000001))
        second = self.write("b.jsonl", event("k2", ts=1700000002))

        def failing(line, state, offset):
            if b"boom" in line:
                raise ValueError("boom")
            return stub_parse(line, state, offset)

        budget = first.stat().st_size
        self.sources = [self.source(parse=failing)]
        self.assertEqual(self.scan(budget=budget), budget)
        self.assertEqual(self.keys(), [])
        self.assertNotIn(str(second), self.files())
        self.sources = [self.source()]
        self.assertGreater(self.scan(), 0)
        self.assertEqual(self.keys(), ["boom", "k1", "k2"])
        self.assertIn(str(second), self.files())

    def test_failing_file_does_not_starve_later_files(self):
        first = self.write("a.jsonl", event("k1") + event("boom", ts=1700000001))
        second = self.write("b.jsonl", event("k2", ts=1700000002))

        def failing(line, state, offset):
            if b"boom" in line:
                raise ValueError("boom")
            return stub_parse(line, state, offset)

        self.sources = [self.source(parse=failing)]
        budget = first.stat().st_size
        self.assertEqual(self.scan(now=NOW, budget=budget), budget)
        self.assertEqual(self.keys(), [])
        self.assertGreater(self.scan(now=NOW + 1, budget=budget), 0)
        self.assertEqual(self.keys(), ["k1", "k2"])
        self.assertIn(str(second), self.files())

    def test_failing_file_does_not_starve_later_sources(self):
        first = self.write("one/a.jsonl", event("k1") + event("boom", ts=1700000001))
        second = self.write("two/b.jsonl", event("k2", ts=1700000002))

        def failing(line, state, offset):
            if b"boom" in line:
                raise ValueError("boom")
            return stub_parse(line, state, offset)

        self.sources = [self.source(parse=failing, root=self.logs / "one"), self.source(root=self.logs / "two")]
        budget = first.stat().st_size
        self.assertEqual(self.scan(now=NOW, budget=budget), budget)
        self.assertEqual(self.keys(), [])
        self.assertGreater(self.scan(now=NOW + 1, budget=budget), 0)
        self.assertEqual(self.keys(), ["k1", "k2"])
        self.assertIn(str(second), self.files())

    def test_failed_file_rolls_back_and_resumes(self):
        path = self.write("a.jsonl", event("k1") + event("boom", ts=1700000001) + event("k2", ts=1700000002))

        def failing(line, state, offset):
            if b"boom" in line:
                raise ValueError("boom")
            return stub_parse(line, state, offset)

        self.sources = [self.source(parse=failing)]
        self.assertGreater(self.scan(), 0)
        self.assertEqual(self.keys(), [])
        self.assertEqual(self.offset(path), 0)
        self.sources = [self.source()]
        self.assertGreater(self.scan(), 0)
        self.assertEqual(self.keys(), ["boom", "k1", "k2"])

    def test_truncated_file_restarts_and_clears_state(self):
        path = self.write("a.jsonl", event("k1") + event("k2"))
        self.scan()
        self.assertEqual(self.state(path), {"lines": 2})
        path.write_text(event("k3"))
        self.scan()
        self.assertEqual(self.keys(), ["k1", "k2", "k3"])
        self.assertEqual(self.state(path), {"lines": 1})
        self.assertEqual(self.offset(path), path.stat().st_size)

    def test_replaced_inode_restarts(self):
        path = self.write("a.jsonl", event("k1"))
        self.scan()
        replacement = self.write("replacement.jsonl", event("k2-with-a-longer-key"))
        os.replace(replacement, path)
        self.scan()
        self.assertEqual(self.keys(), ["k1", "k2-with-a-longer-key"])
        self.assertEqual(self.offset(path), path.stat().st_size)

    def test_deleted_file_row_is_dropped(self):
        path = self.write("a.jsonl", event("k1"))
        self.scan()
        path.unlink()
        self.scan()
        self.assertEqual(self.files(), {})
        self.assertEqual(self.keys(), ["k1"])

    def test_prunes_events_older_than_31_days(self):
        now = 1700000000.0
        self.write("a.jsonl", event("old", ts=now - 40 * 86400) + event("recent", ts=now - 86400))
        self.scan(now=now)
        self.assertEqual(self.keys(), ["recent"])
        self.scan(now=now)
        self.assertEqual(self.keys(), ["recent"])

    def test_discovery_skips_stale_files(self):
        now = 1700000000.0
        path = self.write("a.jsonl", event("k1"))
        stale = now - 40 * 86400
        os.utime(path, (stale, stale))
        self.scan(now=now)
        self.assertEqual(self.files(), {})
        self.assertEqual(self.keys(), [])

    def test_killed_run_rolls_back_and_resumes(self):
        log = self.write("a.jsonl", event("k1") + event("die", ts=1700000001) + event("k2", ts=1700000002))
        database = self.home / "killed" / "usage.db"
        script = (
            "import json, os, signal, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import usage_scan\n"
            "def parse(line, state, offset):\n"
            "    record = json.loads(line)\n"
            "    if record['key'] == 'die':\n"
            "        os.kill(os.getpid(), signal.SIGKILL)\n"
            "    state['lines'] = state.get('lines', 0) + 1\n"
            "    return [{'key': record['key'], 'ts': record['ts']}]\n"
            "connection = usage_scan.open_database(sys.argv[2])\n"
            "usage_scan.scan(connection, [usage_scan.Source('stub', (sys.argv[3],), parse)], now=1700000000.0)\n"
        )
        killed = subprocess.run([sys.executable, "-c", script, str(ROOT), str(database), str(log)],
                                capture_output=True, text=True)
        self.assertEqual(killed.returncode, -signal.SIGKILL, killed.stderr)
        connection = usage_scan.open_database(str(database))
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT count(*) FROM files").fetchone()[0], 0)
        usage_scan.scan(connection, [usage_scan.Source("stub", (str(log),), stub_parse)], now=NOW)
        rows = connection.execute("SELECT key FROM events ORDER BY key").fetchall()
        self.assertEqual([row[0] for row in rows], ["die", "k1", "k2"])
        row = connection.execute("SELECT offset, state FROM files").fetchone()
        self.assertEqual(row[0], log.stat().st_size)
        self.assertEqual(json.loads(row[1]), {"lines": 3})


class EdgeCaseTests(ScanCase):
    def test_missing_root_scan_is_empty(self):
        self.sources = [self.source(root=self.home / "missing")]
        self.assertEqual(self.scan(), 0)
        self.assertEqual(self.keys(), [])
        self.assertEqual(self.files(), {})

    def test_empty_file(self):
        path = self.write("a.jsonl", "")
        self.assertEqual(self.scan(), 0)
        self.assertEqual(self.keys(), [])
        self.assertIn(str(path), self.files())

    @unittest.skipIf(os.geteuid() == 0, "root ignores file permissions")
    def test_unreadable_file_is_skipped(self):
        path = self.write("a.jsonl", event("k1"))
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        self.assertEqual(self.scan(), 0)
        self.assertEqual(self.keys(), [])
        self.assertEqual(self.files(), {})

    @unittest.skipIf(os.geteuid() == 0, "root ignores file permissions")
    def test_unreadable_file_keeps_its_row(self):
        path = self.write("a.jsonl", event("k1"))
        self.scan()
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        self.scan()
        self.assertEqual(self.keys(), ["k1"])
        self.assertIn(str(path), self.files())

    def test_oversized_line_is_skipped(self):
        with mock.patch.object(usage_scan, "MAX_LINE_BYTES", 64):
            path = self.write("a.jsonl", event("k1") + "x" * 200 + "\n" + event("k2"))
            self.scan()
        self.assertEqual(self.keys(), ["k1", "k2"])
        self.assertEqual(self.offset(path), path.stat().st_size)

    def test_oversized_line_resumes_across_budget(self):
        with mock.patch.object(usage_scan, "MAX_LINE_BYTES", 64):
            path = self.write("a.jsonl", "x" * 300 + "\n" + event("k1"))
            budget = 100
            reads = [self.scan(budget=budget)]
            self.assertEqual(reads[0], budget)
            self.assertEqual(self.offset(path), 0)
            self.assertEqual(self.state(path), {"_skip": budget})
            for _ in range(10):
                reads.append(self.scan(budget=budget))
                if reads[-1] == 0:
                    break
        self.assertEqual(self.keys(), ["k1"])
        self.assertEqual(self.offset(path), path.stat().st_size)
        self.assertEqual(self.state(path), {"lines": 1})
        self.assertTrue(all(read <= budget for read in reads))


class PathTests(unittest.TestCase):
    def test_database_path_follows_xdg_cache_home(self):
        self.assertEqual(usage_scan.database_path("/home/x", {"XDG_CACHE_HOME": "/tmp/cache"}),
                         "/tmp/cache/omarchy-ai-usage/usage.db")
        self.assertEqual(usage_scan.database_path("/home/x", {}), "/home/x/.cache/omarchy-ai-usage/usage.db")


if __name__ == "__main__":
    unittest.main()
