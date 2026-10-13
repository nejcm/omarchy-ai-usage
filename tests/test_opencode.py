from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from support import FakeRequest, ProviderCase, load, write
from providers import common, opencode


class OpenCodeTests(ProviderCase):
    AUTH = ".local/share/opencode/auth.json"

    def test_valid(self):
        write(self.home, self.AUTH, {"opencode-go": {"type": "api", "key": "SECRET-KEY"}})
        request = FakeRequest({"": common.Response(200, load("opencode_usage.json"))})
        row = opencode.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(row["plan"], "Go")
        self.assertEqual([m["label"] for m in row["metrics"]], ["Session", "Weekly", "Monthly"])
        self.assertEqual([m["percent"] for m in row["metrics"]], [0.0, 7.0, 3.0])
        self.assertNotIn("SECRET-KEY", json.dumps(row))

    def test_missing_auth(self):
        self.assertEqual(opencode.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_malformed_auth(self):
        write(self.home, self.AUTH, "{not json")
        self.assertEqual(opencode.collect(FakeRequest({}), self.home, {})["error"], "malformed-auth")

    def test_entry_not_a_dict_is_not_signed_in(self):
        write(self.home, self.AUTH, {"opencode-go": "nonsense"})
        self.assertEqual(opencode.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_malformed_usage_does_not_raise(self):
        self.assertEqual(opencode.parse({"usage": "bad"}), [])
        self.assertEqual(opencode.parse({"usage": {"rolling": "bad"}}), [])

    def test_idle_rolling_placeholder_suppressed(self):
        soon = (datetime.now(timezone.utc) + timedelta(seconds=opencode.SESSION_SECONDS)).isoformat().replace("+00:00", "Z")
        genuine = (datetime.now(timezone.utc) + timedelta(seconds=10800)).isoformat().replace("+00:00", "Z")
        payload = {"usage": {"rolling": {"percent": 0, "resetsAt": soon},
                             "weekly": {"percent": 7, "resetsAt": genuine}}}
        metrics = opencode.parse(payload)
        self.assertEqual(metrics[0]["label"], "Session")
        self.assertEqual(metrics[0]["resetsAt"], "")
        self.assertEqual(metrics[1]["resetsAt"], common.reset_iso(genuine))

    def test_expired_auth(self):
        write(self.home, self.AUTH, {"opencode-go": {"key": "SECRET-KEY"}})
        row = opencode.collect(FakeRequest({"": common.Response(401, None)}), self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)

    def test_no_subscription(self):
        write(self.home, self.AUTH, {"opencode-go": {"key": "SECRET-KEY"}})
        row = opencode.collect(FakeRequest({"": common.Response(403, None)}), self.home, {})
        self.assertEqual(row["status"], common.UNAVAILABLE)
        self.assertEqual(row["error"], "no-subscription")

    def test_rate_limited(self):
        write(self.home, self.AUTH, {"opencode-go": {"key": "SECRET-KEY"}})
        row = opencode.collect(FakeRequest({"": common.Response(429, None)}), self.home, {})
        self.assertEqual(row["status"], common.RATE_LIMITED)

    def test_xdg_data_home(self):
        env = {"XDG_DATA_HOME": str(Path(self.home) / "xdg")}
        write(self.home, "xdg/opencode/auth.json", {"opencode-go": {"key": "SECRET-KEY"}})
        request = FakeRequest({"": common.Response(200, load("opencode_usage.json"))})
        self.assertEqual(opencode.collect(request, self.home, env)["status"], common.OK)


if __name__ == "__main__":
    unittest.main()
