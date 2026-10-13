from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from support import FUTURE_EXP, jwt, make_jwt
from providers import claude, common
import providers as providers_pkg


class CommonTests(unittest.TestCase):
    def test_percent_clamps_and_parses(self):
        self.assertEqual(common.percent("42%"), 42.0)
        self.assertEqual(common.percent(150), 100.0)
        self.assertIsNone(common.percent(None))
        self.assertIsNone(common.percent("nope"))
        self.assertIsNone(common.metric("x", common.percent("bad")))

    def test_percent_rejects_nonfinite(self):
        for value in ("NaN", "Infinity", "-Infinity", float("inf"), float("nan")):
            self.assertIsNone(common.percent(value))

    def test_reset_iso_epochs(self):
        self.assertTrue(common.reset_iso(1791732908).startswith("2026-"))
        self.assertTrue(common.reset_iso(1793080672462).startswith("2026-"))
        self.assertEqual(common.reset_iso(""), "")
        self.assertEqual(common.reset_iso("garbage"), "")

    def test_number(self):
        for value in (None, True, False, "bad", "", [], {}, "NaN", "Infinity", "-Infinity", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(common.number(value))
        for value, expected in ((0, 0.0), (-1.5, -1.5), (" 42.5 ", 42.5), (1e308, 1e308)):
            with self.subTest(value=value):
                self.assertEqual(common.number(value), expected)

    def test_parse_time(self):
        expected = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for value in (1767225600, 1767225600000, "1767225600", "1767225600000",
                      "2026-01-01T00:00:00Z", "2026-01-01T00:00:00", "2026-01-01T02:00:00+02:00"):
            with self.subTest(value=value):
                self.assertEqual(common.parse_time(value), expected)
                self.assertEqual(common.reset_iso(value), "2026-01-01T00:00:00Z")
        for value in (None, "", "bad", True, False, float("nan"), float("inf"), 1e308):
            with self.subTest(value=value):
                self.assertIsNone(common.parse_time(value))
                self.assertEqual(common.reset_iso(value), "")

    def test_finish_row_shape(self):
        for metrics, status, error in (([], common.UNAVAILABLE, "no-data"),
                                       ([common.metric("Session", 42.0, "2030-01-01T00:00:00Z")], common.OK, "")):
            with self.subTest(status=status), mock.patch.object(common, "now_iso", return_value="stamp"):
                self.assertEqual(common.finish(claude.PROVIDER, metrics, "Max"), {
                    "provider": "claude", "name": "Claude Code", "abbrev": "C", "plan": "Max",
                    "status": status, "error": error, "metrics": metrics,
                    "resetAt": "2030-01-01T00:00:00Z" if metrics else "", "refreshedAt": "stamp",
                })

    def test_claude_config_paths_keep_whitespace_behavior(self):
        for override, claude_dir, zai_dir in ((None, "/home/test/.claude", "/home/test/.claude"),
                                              ("", "/home/test/.claude", "/home/test/.claude"),
                                              ("   ", "   ", "/home/test/.claude"),
                                              (" /custom ", " /custom ", "/custom"),
                                              ("/custom", "/custom", "/custom")):
            with self.subTest(override=override):
                self.assertEqual(claude.credentials_path("/home/test", {"CLAUDE_CONFIG_DIR": override}),
                                 claude_dir + "/.credentials.json")
                self.assertEqual(providers_pkg.zai.claude_settings_path("/home/test", {"CLAUDE_CONFIG_DIR": override}),
                                 zai_dir + "/settings.json")

    def test_jwt_exp_and_non_dict_payload(self):
        self.assertEqual(common.jwt_exp(make_jwt(FUTURE_EXP)), FUTURE_EXP)
        self.assertIsNone(common.jwt_exp("not-a-jwt"))
        self.assertIsNone(common.jwt_exp(jwt({"alg": "none"}) + "." + jwt("scalar") + ".sig"))


if __name__ == "__main__":
    unittest.main()
