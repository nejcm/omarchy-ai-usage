import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from support import FakeRequest, ProviderCase, load, write
from providers import common, antigravity

_REAL_READ_KEYRING = antigravity._read_keyring


class AntigravityTests(ProviderCase):
    AUTH = ".gemini/antigravity-cli/antigravity-oauth-token"

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(antigravity, "_read_keyring", return_value=None)
        self.keyring = patcher.start()
        self.addCleanup(patcher.stop)

    def valid_auth(self):
        return {"token": {"access_token": "SECRET-TOKEN", "token_type": "Bearer",
                          "refresh_token": "r", "expiry": "2030-01-01T00:00:00Z"},
                "auth_method": "consumer"}

    def routes(self, summary=None):
        return {"retrieveUserQuotaSummary": common.Response(200, summary or load("antigravity_usage.json"))}

    def labels(self, metrics):
        return [(m["label"], round(m["percent"], 6), m["windowMinutes"]) for m in metrics]

    def test_valid(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest(self.routes())
        row = antigravity.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(self.labels(row["metrics"]), [
            ("Gemini", 8.0, 300), ("Gemini Weekly", 14.0, 10080),
            ("Claude/GPT Weekly", 0.0, 10080), ("Gemini 4 Argon Weekly", 0.0, 10080)])
        self.assertEqual(row["metrics"][0]["resetsAt"], "2026-08-23T04:25:14Z")
        self.assertEqual(len(request.calls), 1)
        self.assertIn("daily-cloudcode-pa.googleapis.com", request.calls[0]["url"])
        self.assertEqual(request.calls[0]["method"], "POST")
        self.assertEqual(request.calls[0]["headers"]["Authorization"], "Bearer SECRET-TOKEN")
        self.assertTrue(request.calls[0]["headers"]["User-Agent"].startswith("antigravity/hub/"))

    def untracked(self):
        now = datetime.now(timezone.utc)
        def bucket(bucket_id, window, minutes):
            reset = (now + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
            return {"bucketId": bucket_id, "window": window, "remainingFraction": 1, "resetTime": reset}
        return {"groups": [{"buckets": [bucket("gemini-weekly", "weekly", 10080), bucket("gemini-5h", "5h", 300)]},
                           {"buckets": [bucket("3p-weekly", "weekly", 10080), bucket("3p-5h", "5h", 300)]}]}

    def test_untracked_replica_answer_is_retried(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest({"retrieveUserQuotaSummary": [
            common.Response(200, self.untracked()), common.Response(200, load("antigravity_usage.json"))]})
        row = antigravity.collect(request, self.home, {})
        self.assertEqual(self.labels(row["metrics"])[:2], [("Gemini", 8.0, 300), ("Gemini Weekly", 14.0, 10080)])
        self.assertEqual(len(request.calls), 2)

    def test_untracked_answer_accepted_after_attempts(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest({"retrieveUserQuotaSummary": common.Response(200, self.untracked())})
        row = antigravity.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(self.labels(row["metrics"])[0], ("Gemini", 0.0, 300))
        self.assertEqual(len(request.calls), antigravity.ATTEMPTS)

    def test_fixed_reset_is_tracked(self):
        payload = self.untracked()
        payload["groups"][0]["buckets"][1]["resetTime"] = "2030-01-01T00:00:00Z"
        self.assertFalse(antigravity._is_untracked(payload, datetime.now(timezone.utc)))

    def test_used_claude_session_is_shown(self):
        payload = load("antigravity_usage.json")
        payload["groups"][1]["buckets"][1]["remainingFraction"] = 0.8
        self.assertIn(("Claude/GPT", 20.0, 300), self.labels(antigravity.parse(payload)))

    def test_idle_gemini_session_is_shown(self):
        payload = load("antigravity_usage.json")
        payload["groups"][0]["buckets"][1]["remainingFraction"] = 1
        self.assertEqual(self.labels(antigravity.parse(payload))[0], ("Gemini", 0.0, 300))

    def test_window_inferred_from_bucket_id(self):
        payload = {"groups": [{"buckets": [{"bucketId": "gemini-5h", "remainingFraction": 0.5},
                                           {"bucketId": "gemini-weekly", "remainingFraction": 0.9}]}]}
        self.assertEqual(self.labels(antigravity.parse(payload)), [("Gemini", 50.0, 300), ("Gemini Weekly", 10.0, 10080)])

    def test_unknown_window_and_disabled_buckets_ignored(self):
        payload = load("antigravity_usage.json")
        payload["groups"][0]["buckets"].append({"bucketId": "gemini-image-daily", "window": "daily", "remainingFraction": 0.1})
        payload["groups"][2]["buckets"][0]["disabled"] = True
        self.assertEqual([m["label"] for m in antigravity.parse(payload)],
                         ["Gemini", "Gemini Weekly", "Claude/GPT Weekly"])

    def test_missing_fraction_drops_line(self):
        payload = load("antigravity_usage.json")
        del payload["groups"][0]["buckets"][1]["remainingFraction"]
        self.assertNotIn("Gemini", [m["label"] for m in antigravity.parse(payload)])

    def test_duplicate_bucket_first_wins(self):
        payload = load("antigravity_usage.json")
        payload["groups"][1]["buckets"].append({"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0.5})
        self.assertAlmostEqual(antigravity.parse(payload)[0]["percent"], 8.0, places=6)

    def test_fraction_clamped(self):
        for value, expected in ((-1, 100.0), (2, 0.0), (-1e308, 100.0), (1e308, 0.0)):
            with self.subTest(value=value):
                payload = {"groups": [{"buckets": [{"bucketId": "gemini-weekly", "remainingFraction": value}]}]}
                self.assertEqual([m["percent"] for m in antigravity.parse(payload)], [expected])

    def test_fraction_keeps_precision(self):
        payload = {"groups": [{"buckets": [{"bucketId": "gemini-weekly", "remainingFraction": 0.204}]}]}
        percent = antigravity.parse(payload)[0]["percent"]
        self.assertAlmostEqual(percent, 79.6, places=6)
        self.assertLess(percent, 80)

    def test_malformed_usage_does_not_raise(self):
        self.assertEqual(antigravity.parse({"groups": "bad"}), [])
        self.assertEqual(antigravity.parse({"groups": [None, {"buckets": "x"}]}), [])
        self.assertEqual(antigravity.parse({"groups": [{"buckets": [None, {"bucketId": "gemini-5h",
                                                                           "remainingFraction": "bad"}]}]}), [])

    def test_missing_auth(self):
        self.assertEqual(antigravity.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_keyring_used_when_file_missing(self):
        self.keyring.return_value = json.dumps(self.valid_auth())
        self.assertEqual(antigravity.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)

    def test_malformed_keyring_secret(self):
        self.keyring.return_value = "{not json"
        self.assertEqual(antigravity.collect(FakeRequest({}), self.home, {})["error"], "malformed-auth")

    def test_file_takes_precedence_over_keyring(self):
        write(self.home, self.AUTH, self.valid_auth())
        antigravity.collect(FakeRequest(self.routes()), self.home, {})
        self.keyring.assert_not_called()

    def test_non_utf8_auth_file(self):
        write(self.home, self.AUTH, "").write_bytes(b"\xff\xfe")
        self.assertEqual(antigravity.collect(FakeRequest({}), self.home, {})["error"], "malformed-auth")

    def test_keyring_lookup_failure_is_none(self):
        with mock.patch.object(antigravity.subprocess, "run",
                               return_value=mock.Mock(returncode=1, stdout="")) as run:
            self.assertIsNone(_REAL_READ_KEYRING({"DBUS_SESSION_BUS_ADDRESS": "x"}))
        self.assertEqual(run.call_args.kwargs["env"], {"DBUS_SESSION_BUS_ADDRESS": "x"})
        with mock.patch.object(antigravity.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(_REAL_READ_KEYRING({}))

    def test_malformed_auth(self):
        write(self.home, self.AUTH, "{not json")
        self.assertEqual(antigravity.collect(FakeRequest({}), self.home, {})["error"], "malformed-auth")

    def test_token_without_access_token_is_not_signed_in(self):
        write(self.home, self.AUTH, {"token": {"refresh_token": "r"}, "auth_method": "consumer"})
        request = FakeRequest(self.routes())
        self.assertEqual(antigravity.collect(request, self.home, {})["status"], common.NOT_SIGNED_IN)
        self.assertEqual(request.calls, [])

    def test_root_level_access_token_is_read(self):
        write(self.home, self.AUTH, {"access_token": "SECRET-TOKEN"})
        self.assertEqual(antigravity.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)

    def test_expired_token_is_refreshed_in_memory(self):
        path = write(self.home, self.AUTH, {"token": {"access_token": "OLD", "refresh_token": "r",
                                                     "expiry": "2001-09-09T01:46:40Z"}})
        before = path.read_text()
        routes = dict(self.routes(), **{"oauth2.googleapis.com/token": common.Response(200, {"access_token": "NEW"})})
        request = FakeRequest(routes)
        row = antigravity.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(request.calls[1]["headers"]["Authorization"], "Bearer NEW")
        self.assertEqual(path.read_text(), before)

    def test_rejected_refresh_is_expired(self):
        write(self.home, self.AUTH, {"token": {"access_token": "OLD", "refresh_token": "r",
                                              "expiry": "2001-09-09T01:46:40Z"}})
        routes = dict(self.routes(), **{"oauth2.googleapis.com/token": common.Response(400, None)})
        request = FakeRequest(routes)
        row = antigravity.collect(request, self.home, {})
        self.assertEqual((row["status"], row["error"]), (common.EXPIRED, "auth-expired"))
        self.assertEqual(len(request.calls), 1)

    def test_expired_expiry(self):
        write(self.home, self.AUTH, {"token": {"access_token": "SECRET-TOKEN", "expiry": "2001-09-09T01:46:40Z"}})
        request = FakeRequest(self.routes())
        row = antigravity.collect(request, self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)
        self.assertEqual(row["error"], "auth-expired")
        self.assertEqual(request.calls, [])

    def test_sign_in_expired_on_401(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = antigravity.collect(FakeRequest({"retrieveUserQuotaSummary": common.Response(401, None)}), self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)

    def test_rate_limited(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = antigravity.collect(FakeRequest({"retrieveUserQuotaSummary": common.Response(429, None)}), self.home, {})
        self.assertEqual(row["status"], common.RATE_LIMITED)

    def test_no_buckets_is_unavailable(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = antigravity.collect(FakeRequest(self.routes({"groups": []})),
                                  self.home, {})
        self.assertEqual(row["status"], common.UNAVAILABLE)

    def test_token_not_in_row(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = antigravity.collect(FakeRequest(self.routes()), self.home, {})
        self.assertNotIn("SECRET-TOKEN", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
