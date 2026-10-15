"""Aggregation and --usage CLI tests; temp cache and fixture homes only."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from support import FIXTURES  # noqa: E402

import usage  # noqa: E402
import local_usage.report  # noqa: E402
import local_usage.scan  # noqa: E402

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc).timestamp()
EMPTY = {"tokens": 0, "output": 0, "sessions": 0, "cacheHit": 0.0,
         "breakdown": {"input": 0, "cacheRead": 0, "cacheWrite": 0, "output": 0, "reasoning": 0},
         "providers": [], "models": []}


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def zero_days(first, count, providers):
    start = date.fromisoformat(first)
    return [{"date": (start + timedelta(days=offset)).isoformat(), "providers": dict.fromkeys(providers, 0)}
            for offset in range(count)]


def zero_weeks(first, count, providers):
    start = date.fromisoformat(first)
    return [{"date": (start + timedelta(days=7 * offset)).isoformat(), "providers": dict.fromkeys(providers, 0)}
            for offset in range(count)]


def golden_document():
    week = {
        "tokens": 1361, "output": 346, "sessions": 3, "cacheHit": 607 / 1672,
        "breakdown": {"input": 1015, "cacheRead": 607, "cacheWrite": 50, "output": 266, "reasoning": 80},
        "providers": [
            {"id": "codex", "tokens": 1050, "output": 150, "sessions": 1, "cacheHit": 400 / 1300,
             "breakdown": {"input": 900, "cacheRead": 400, "cacheWrite": 0, "output": 100, "reasoning": 50}},
            {"id": "claude", "tokens": 311, "output": 196, "sessions": 2, "cacheHit": 207 / 372,
             "breakdown": {"input": 115, "cacheRead": 207, "cacheWrite": 50, "output": 166, "reasoning": 30}},
        ],
        "models": [{"name": "gpt-6.1-sol", "provider": "codex", "tokens": 1050},
                   {"name": "claude-opus-5-5", "provider": "claude", "tokens": 300},
                   {"name": "claude-haiku-4-5", "provider": "claude", "tokens": 11}],
        "days": zero_days("2026-09-26", 7, ["claude", "codex"]),
    }
    week["days"][-2]["providers"] = {"claude": 311, "codex": 1050}
    month = {
        "tokens": 1372, "output": 350, "sessions": 4, "cacheHit": 616 / 1688,
        "breakdown": {"input": 1022, "cacheRead": 616, "cacheWrite": 50, "output": 269, "reasoning": 81},
        "providers": [
            {"id": "codex", "tokens": 1050, "output": 150, "sessions": 1, "cacheHit": 400 / 1300,
             "breakdown": {"input": 900, "cacheRead": 400, "cacheWrite": 0, "output": 100, "reasoning": 50}},
            {"id": "claude", "tokens": 311, "output": 196, "sessions": 2, "cacheHit": 207 / 372,
             "breakdown": {"input": 115, "cacheRead": 207, "cacheWrite": 50, "output": 166, "reasoning": 30}},
            {"id": "opencode", "tokens": 11, "output": 4, "sessions": 1, "cacheHit": 9 / 16,
             "breakdown": {"input": 7, "cacheRead": 9, "cacheWrite": 0, "output": 3, "reasoning": 1}},
        ],
        "models": [{"name": "gpt-6.1-sol", "provider": "codex", "tokens": 1050},
                   {"name": "claude-opus-5-5", "provider": "claude", "tokens": 300},
                   {"name": "claude-haiku-4-5", "provider": "claude", "tokens": 11},
                   {"name": "test-model", "provider": "opencode", "tokens": 11}],
        "days": zero_days("2026-09-03", 30, ["claude", "codex", "opencode"]),
    }
    month["days"][-8]["providers"] = {"claude": 0, "codex": 0, "opencode": 11}
    month["days"][-2]["providers"] = {"claude": 311, "codex": 1050, "opencode": 0}
    half = dict(month, days=zero_weeks("2026-04-04", 26, ["claude", "codex", "opencode"]))
    half["days"][-2]["providers"] = {"claude": 0, "codex": 0, "opencode": 11}
    half["days"][-1]["providers"] = {"claude": 311, "codex": 1050, "opencode": 0}
    year = dict(month, days=zero_weeks("2025-10-04", 52, ["claude", "codex", "opencode"]))
    year["days"][-2]["providers"] = {"claude": 0, "codex": 0, "opencode": 11}
    year["days"][-1]["providers"] = {"claude": 311, "codex": 1050, "opencode": 0}
    return {"usage": {"scanning": False, "windows": {"today": EMPTY, "7d": week, "30d": month,
                                                    "6m": half, "1y": year}}}


class ReportCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.env = {"XDG_CACHE_HOME": str(self.home / "cache")}
        self.connection = local_usage.scan.open_database(local_usage.scan.database_path(str(self.home), self.env))
        self.addCleanup(self.connection.close)

    def set_timezone(self, name):
        previous = os.environ.get("TZ")

        def restore():
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

        self.addCleanup(restore)
        os.environ["TZ"] = name
        time.tzset()

    def add(self, key, ts, provider="claude", session="s", model="m", input=0, cache_read=0, cache_write=0,
            output=0, reasoning=0):
        self.connection.execute(
            "INSERT OR REPLACE INTO events(key, ts, provider, session, model, input, cache_read, cache_write,"
            " output, reasoning) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (key, ts, provider, session, model, input, cache_read, cache_write, output, reasoning))
        self.connection.commit()

    def windows(self, now=NOW, providers=None):
        return local_usage.report.windows(self.connection, now, providers)


class SummaryTests(ReportCase):
    def setUp(self):
        super().setUp()
        self.set_timezone("UTC")

    def test_summary_and_breakdown(self):
        self.add("a", NOW, session="s1", model="m1", input=10, cache_read=30, cache_write=5, output=4, reasoning=6)
        self.add("b", NOW, session="s1", model="m2", input=1, output=2)
        self.add("c", NOW - 3 * 86400, session="s2", model="m1", input=100)
        self.add("d", NOW - 40 * 86400, session="s3", model="m9", input=1000)
        today = self.windows()["today"]
        self.assertEqual(today["tokens"], 23)
        self.assertEqual(today["output"], 12)
        self.assertEqual(today["sessions"], 1)
        self.assertEqual(today["cacheHit"], 30 / 46)
        self.assertEqual(today["breakdown"], {"input": 11, "cacheRead": 30, "cacheWrite": 5, "output": 6, "reasoning": 6})
        self.assertEqual(today["providers"], [{
            "id": "claude", "tokens": 23, "output": 12, "sessions": 1, "cacheHit": 30 / 46,
            "breakdown": {"input": 11, "cacheRead": 30, "cacheWrite": 5, "output": 6, "reasoning": 6}}])
        self.assertEqual(today["models"], [{"name": "m1", "provider": "claude", "tokens": 20},
                                           {"name": "m2", "provider": "claude", "tokens": 3}])
        week = self.windows()["7d"]
        self.assertEqual(week["tokens"], 123)
        self.assertEqual(week["sessions"], 2)

    def test_future_events_are_excluded(self):
        self.add("now", NOW, input=5)
        self.add("future", NOW + 86400, input=100)
        windows = self.windows()
        self.assertEqual(windows["today"]["tokens"], 5)
        self.assertEqual(windows["7d"]["tokens"], 5)
        self.assertEqual(windows["30d"]["tokens"], 5)
        self.assertEqual(sum(day["providers"].get("claude", 0) for day in windows["7d"]["days"]), 5)

    def test_concurrent_commit_cannot_split_the_snapshot(self):
        self.add("a", NOW, model="m1", input=5)
        writer = sqlite3.connect(local_usage.scan.database_path(str(self.home), self.env))
        writer.execute("PRAGMA busy_timeout = 0")
        self.addCleanup(writer.close)
        attempted = []

        class Interleaving:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, parameters=()):
                if "GROUP BY provider, model" in sql and not attempted:
                    try:
                        writer.execute("INSERT INTO events(key, ts, provider, session, model, input, cache_read,"
                                       " cache_write, output, reasoning)"
                                       " VALUES('late', ?, 'claude', 's', 'm2', 7, 0, 0, 0, 0)", (NOW,))
                        writer.commit()
                        attempted.append("committed")
                    except sqlite3.OperationalError:
                        attempted.append("blocked")
                return self.connection.execute(sql, parameters)

        windows = local_usage.report.windows(Interleaving(self.connection), NOW)
        self.assertEqual(windows["today"]["tokens"], 5)
        for name in ("today", "7d", "30d"):
            self.assertEqual(windows[name]["tokens"], sum(row["tokens"] for row in windows[name]["models"]))
        self.assertEqual(attempted, ["blocked"])

    def test_provider_filter(self):
        self.add("a", NOW, provider="claude", input=5)
        self.add("b", NOW, provider="codex", input=9)
        self.add("c", NOW, provider="opencode", input=7)
        today = self.windows(providers=["codex"])["today"]
        self.assertEqual(today["tokens"], 9)
        self.assertEqual(today["providers"], [{
            "id": "codex", "tokens": 9, "output": 0, "sessions": 1, "cacheHit": 0.0,
            "breakdown": {"input": 9, "cacheRead": 0, "cacheWrite": 0, "output": 0, "reasoning": 0}}])
        self.assertEqual(today["sessions"], 1)
        self.assertEqual(self.windows(providers=[])["today"]["providers"], [])

    def test_provider_summaries_add_up_to_the_window(self):
        self.add("a", NOW, provider="claude", session="s1", input=100, cache_read=200, cache_write=50,
                 output=30, reasoning=10)
        self.add("b", NOW, provider="claude", session="s2", input=5, output=5)
        self.add("c", NOW, provider="codex", session="s3", input=300, cache_read=100, output=40, reasoning=20)
        self.add("d", NOW - 3 * 86400, provider="opencode", session="s4", input=10)
        self.add("z", NOW, provider="zai", session="s5")
        week = self.windows()["7d"]
        summaries = {entry["id"]: entry for entry in week["providers"]}
        self.assertEqual(summaries["claude"]["cacheHit"], 200 / 355)
        self.assertEqual(summaries["codex"]["cacheHit"], 100 / 400)
        self.assertEqual(summaries["opencode"]["cacheHit"], 0.0)
        self.assertEqual(summaries["zai"]["cacheHit"], 0.0)
        for field in ("tokens", "output", "sessions"):
            self.assertEqual(sum(entry[field] for entry in week["providers"]), week[field])
        for bucket in week["breakdown"]:
            self.assertEqual(sum(entry["breakdown"][bucket] for entry in week["providers"]),
                             week["breakdown"][bucket])
        self.assertEqual(summaries["claude"]["breakdown"],
                         {"input": 105, "cacheRead": 200, "cacheWrite": 50, "output": 35, "reasoning": 10})
        self.assertEqual(summaries["codex"]["sessions"], 1)
        self.assertEqual(summaries["claude"]["sessions"], 2)


class WindowTests(ReportCase):
    def setUp(self):
        super().setUp()
        self.set_timezone("Europe/Ljubljana")

    def test_midnight_bucketing(self):
        self.add("early", at("2026-10-01T21:30:00Z"), input=3)
        self.add("late", at("2026-10-01T22:30:00Z"), input=5)
        windows = self.windows()
        self.assertEqual(windows["today"]["tokens"], 5)
        self.assertEqual(windows["7d"]["days"][-2:],
                         [{"date": "2026-10-01", "providers": {"claude": 3}},
                          {"date": "2026-10-02", "providers": {"claude": 5}}])

    def test_window_boundary_is_local(self):
        now = at("2026-10-01T22:30:00Z")
        self.add("inside", at("2026-09-25T22:30:00Z"), input=7)
        self.add("outside", at("2026-09-25T21:30:00Z"), input=100)
        windows = self.windows(now=now)
        self.assertEqual(windows["7d"]["tokens"], 7)
        self.assertEqual(windows["30d"]["tokens"], 107)
        self.assertEqual(windows["today"]["tokens"], 0)

    def test_day_windows_and_zero_filling(self):
        windows = self.windows()
        self.assertNotIn("days", windows["today"])
        self.assertEqual(len(windows["7d"]["days"]), 7)
        self.assertEqual(len(windows["30d"]["days"]), 30)
        self.assertEqual(len(windows["6m"]["days"]), 26)
        self.assertEqual(len(windows["1y"]["days"]), 52)
        self.assertEqual(windows["7d"]["days"][0]["date"], "2026-09-26")
        self.assertEqual(windows["30d"]["days"][0]["date"], "2026-09-03")
        self.assertEqual(windows["6m"]["days"][0]["date"], "2026-04-04")
        self.assertEqual(windows["1y"]["days"][0]["date"], "2025-10-04")
        self.assertEqual(windows["6m"]["days"][-1]["date"], "2026-09-26")
        self.assertEqual(windows["1y"]["days"][-1]["date"], "2026-09-26")
        self.assertEqual(windows["7d"]["days"][0]["providers"], {})
        self.assertEqual(windows["today"], EMPTY)

    def test_long_windows_bucket_by_week(self):
        self.add("a", at("2026-09-19T10:00:00Z"), provider="claude", input=4)
        self.add("b", at("2026-09-25T10:00:00Z"), provider="claude", input=6)
        self.add("c", at("2026-09-26T10:00:00Z"), provider="codex", input=5)
        self.add("d", at("2026-10-02T10:00:00Z"), provider="claude", input=7)
        for name, count in (("6m", 26), ("1y", 52)):
            days = self.windows()[name]["days"]
            self.assertEqual(len(days), count)
            self.assertEqual(days[-2], {"date": "2026-09-19", "providers": {"claude": 10, "codex": 0}})
            self.assertEqual(days[-1], {"date": "2026-09-26", "providers": {"claude": 7, "codex": 5}})
            self.assertEqual(sum(day["providers"]["claude"] for day in days), 17)
        self.assertEqual(len(self.windows()["7d"]["days"]), 7)


class GoldenTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        previous = os.environ.get("TZ")

        def restore():
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

        self.addCleanup(restore)
        os.environ["TZ"] = "UTC"
        time.tzset()

    def install(self):
        claude = self.home / ".claude" / "projects" / "s" / "transcript.jsonl"
        claude.parent.mkdir(parents=True)
        claude.write_bytes((FIXTURES / "claude_usage.jsonl").read_bytes())
        os.utime(claude, (NOW, NOW))
        codex = self.home / ".codex" / "sessions" / "2026" / "10" / "01" / "session.jsonl"
        codex.parent.mkdir(parents=True)
        codex.write_bytes((FIXTURES / "codex_session.jsonl").read_bytes())
        os.utime(codex, (NOW, NOW))
        created = int(at("2026-09-25T10:00:00Z") * 1000)
        database = self.home / "opencode" / "opencode.db"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(str(database))
        connection.execute("CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT NOT NULL,"
                           " time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL)")
        connection.execute("INSERT INTO message VALUES(?,?,?,?,?)", (
            "msg-oc", "ses-oc", created, created, json.dumps(
                {"role": "assistant", "modelID": "test-model",
                 "tokens": {"input": 7, "output": 3, "reasoning": 1, "cache": {"read": 9, "write": 0}}})))
        connection.commit()
        connection.close()

    def run_cli(self, *extra):
        environment = {"XDG_CACHE_HOME": str(self.home / "cache"), "OPENCODE_DATA_DIR": str(self.home / "opencode"),
                       "CLAUDE_CONFIG_DIR": str(self.home / ".claude"), "CODEX_HOME": str(self.home / ".codex")}
        with mock.patch.dict(os.environ, environment), mock.patch("time.time", return_value=NOW), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = usage.main(["--usage", "--home", str(self.home), *extra])
        return code, json.loads(out.getvalue())

    def test_golden_usage_output(self):
        self.install()
        code, document = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(document, golden_document())

    def test_provider_selection(self):
        self.install()
        _, document = self.run_cli("--provider", "claude")
        windows = document["usage"]["windows"]
        self.assertEqual([row["id"] for row in windows["7d"]["providers"]], ["claude"])
        self.assertEqual([row["name"] for row in windows["7d"]["models"]],
                         ["claude-opus-5-5", "claude-haiku-4-5"])
        self.assertEqual(windows["7d"]["tokens"], 311)
        _, document = self.run_cli("--provider", "cursor")
        self.assertEqual(document["usage"]["windows"]["7d"]["providers"], [])

    def test_scanning_flag_while_budget_is_short(self):
        self.install()
        with mock.patch.object(local_usage.scan, "BUDGET_BYTES", 10):
            _, document = self.run_cli()
        self.assertTrue(document["usage"]["scanning"])


if __name__ == "__main__":
    unittest.main()
