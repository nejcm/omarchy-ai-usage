import json
import unittest

from support import FakeRequest, ProviderCase, load, write
from providers import common, antigravity


class AntigravityTests(ProviderCase):
    AUTH = ".gemini/antigravity-cli/antigravity-oauth-token"

    def valid_auth(self):
        return {"token": {"access_token": "SECRET-TOKEN", "token_type": "Bearer",
                          "refresh_token": "r", "expiry": "2030-01-01T00:00:00Z"},
                "auth_method": "consumer"}

    def routes(self):
        return {"retrieveUserQuotaSummary": common.Response(200, load("antigravity_usage.json"))}

    def test_valid(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest(self.routes())
        row = antigravity.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual([m["label"] for m in row["metrics"]], ["Session", "Weekly", "Claude", "Claude Weekly"])
        for metric, expected in zip(row["metrics"], [8.0, 14.0, 0.0, 0.0]):
            self.assertAlmostEqual(metric["percent"], expected, places=6)
        self.assertEqual(row["metrics"][0]["resetsAt"], "2026-08-23T04:25:14Z")
        self.assertEqual([m["windowMinutes"] for m in row["metrics"]], [300, 10080, 300, 10080])
        self.assertEqual(request.calls[0]["method"], "POST")
        self.assertEqual(request.calls[0]["headers"]["Authorization"], "Bearer SECRET-TOKEN")
        self.assertEqual(request.calls[0]["headers"].get("User-Agent"), "antigravity")

    def test_unknown_bucket_ignored(self):
        payload = load("antigravity_usage.json")
        payload["groups"][0]["buckets"].append({"bucketId": "gemini-image-5h", "remainingFraction": 0.1})
        self.assertEqual([m["label"] for m in antigravity.parse(payload)],
                         ["Session", "Weekly", "Claude", "Claude Weekly"])

    def test_missing_fraction_drops_line(self):
        payload = load("antigravity_usage.json")
        payload["groups"][0]["buckets"][0] = {"bucketId": "gemini-5h"}
        self.assertEqual([m["label"] for m in antigravity.parse(payload)], ["Weekly", "Claude", "Claude Weekly"])

    def test_duplicate_bucket_first_wins(self):
        payload = load("antigravity_usage.json")
        payload["groups"][1]["buckets"].append({"bucketId": "gemini-5h", "remainingFraction": 0.5})
        self.assertAlmostEqual(antigravity.parse(payload)[0]["percent"], 8.0, places=6)

    def test_fraction_clamped(self):
        for value, expected in ((-1, 100.0), (2, 0.0), (-1e308, 100.0), (1e308, 0.0)):
            with self.subTest(value=value):
                payload = {"groups": [{"buckets": [{"bucketId": "gemini-5h", "remainingFraction": value}]}]}
                self.assertEqual([m["percent"] for m in antigravity.parse(payload)], [expected])

    def test_fraction_keeps_precision(self):
        payload = {"groups": [{"buckets": [{"bucketId": "gemini-5h", "remainingFraction": 0.204}]}]}
        percent = antigravity.parse(payload)[0]["percent"]
        self.assertAlmostEqual(percent, 79.6, places=6)
        self.assertLess(percent, 80)

    def test_malformed_usage_does_not_raise(self):
        self.assertEqual(antigravity.parse({"groups": "bad"}), [])
        self.assertEqual(antigravity.parse({"groups": [None, {"buckets": "x"}]}), [])
        self.assertEqual(antigravity.parse({"groups": [{"buckets": [None, {"bucketId": "gemini-5h",
                                                                           "remainingFraction": "bad"}]}]}), [])

    def test_malformed_group_keeps_valid_buckets(self):
        payload = load("antigravity_usage.json")
        payload["groups"].append({"buckets": 42})
        self.assertEqual([m["label"] for m in antigravity.parse(payload)],
                         ["Session", "Weekly", "Claude", "Claude Weekly"])

    def test_missing_auth(self):
        self.assertEqual(antigravity.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

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
        row = antigravity.collect(FakeRequest({"retrieveUserQuotaSummary": common.Response(200, {"groups": []})}),
                                  self.home, {})
        self.assertEqual(row["status"], common.UNAVAILABLE)

    def test_token_not_in_row(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = antigravity.collect(FakeRequest(self.routes()), self.home, {})
        self.assertNotIn("SECRET-TOKEN", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
