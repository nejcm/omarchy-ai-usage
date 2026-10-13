from __future__ import annotations

import unittest

from support import FUTURE_EXP, PAST_EXP, FakeRequest, ProviderCase, load, make_jwt, write
from providers import common, cursor


class CursorTests(ProviderCase):
    AUTH = ".config/cursor/auth.json"

    def valid_auth(self):
        return {"accessToken": make_jwt(FUTURE_EXP), "refreshToken": "r"}

    def routes(self):
        return {"GetCurrentPeriodUsage": common.Response(200, load("cursor_usage.json")),
                "GetPlanInfo": common.Response(200, load("cursor_plan.json"))}

    def test_valid(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = cursor.collect(FakeRequest(self.routes()), self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(row["plan"], "Free")
        self.assertEqual(row["metrics"][0]["label"], "Total usage")
        self.assertEqual([m["percent"] for m in row["metrics"]], [2.5, 5.0, 0.0])

    def test_derived_total_when_percentage_absent(self):
        write(self.home, self.AUTH, self.valid_auth())
        routes = {"GetCurrentPeriodUsage": common.Response(200, load("cursor_spend.json"))}
        row = cursor.collect(FakeRequest(routes), self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(row["metrics"][0]["label"], "Total usage")
        self.assertEqual(row["metrics"][0]["percent"], 50.0)

    def test_remaining_is_converted_to_used(self):
        payload = load("cursor_spend.json")
        del payload["planUsage"]["totalSpend"]
        for remaining, used in ((2000, 0), (1500, 25), (500, 75), (0, 100)):
            with self.subTest(remaining=remaining):
                payload["planUsage"]["remaining"] = remaining
                self.assertEqual(cursor.parse(payload)[0]["percent"], used)

    def test_missing_auth(self):
        self.assertEqual(cursor.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_malformed_auth(self):
        write(self.home, self.AUTH, "{not json")
        self.assertEqual(cursor.collect(FakeRequest({}), self.home, {})["error"], "malformed-auth")

    def test_malformed_plan_usage_does_not_raise(self):
        self.assertEqual(cursor.parse({"planUsage": "bad"}), [])

    def test_nonfinite_spend_is_ignored(self):
        for spent in ("NaN", "-Infinity", "Infinity"):
            write(self.home, self.AUTH, self.valid_auth())
            routes = {"GetCurrentPeriodUsage": common.Response(200, {"planUsage": {"limit": 100, "totalSpend": spent}})}
            row = cursor.collect(FakeRequest(routes), self.home, {})
            self.assertNotEqual(row["status"], common.OK)
            self.assertEqual(row["metrics"], [])

    def test_expired_auth(self):
        write(self.home, self.AUTH, {"accessToken": make_jwt(PAST_EXP)})
        request = FakeRequest(self.routes())
        row = cursor.collect(request, self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)
        self.assertEqual(request.calls, [])

    def test_rate_limited(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = cursor.collect(FakeRequest({"": common.Response(429, None)}), self.home, {})
        self.assertEqual(row["status"], common.RATE_LIMITED)


if __name__ == "__main__":
    unittest.main()
