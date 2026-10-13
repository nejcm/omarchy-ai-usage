from __future__ import annotations

import unittest

from support import FUTURE_EXP, PAST_EXP, FakeRequest, ProviderCase, load, make_jwt, write
from providers import codex, common


class CodexTests(ProviderCase):
    AUTH = ".codex/auth.json"

    def valid_auth(self):
        return {"auth_mode": "chatgpt",
                "tokens": {"access_token": make_jwt(FUTURE_EXP), "account_id": "acct-1", "refresh_token": "r"}}

    def test_valid(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest({"": common.Response(200, load("codex_usage.json"))})
        row = codex.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(row["plan"], "Pro 200")
        self.assertEqual([m["percent"] for m in row["metrics"]], [3.0, 8.0])
        self.assertEqual(request.calls[0]["headers"].get("ChatGPT-Account-Id"), "acct-1")

    def test_weekly_only_primary_is_weekly(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest({"": common.Response(200, load("codex_weekly_primary.json"))})
        row = codex.collect(request, self.home, {})
        self.assertEqual([m["label"] for m in row["metrics"]], ["Weekly"])
        self.assertEqual(row["metrics"][0]["percent"], 8.0)

    def test_missing_auth(self):
        self.assertEqual(codex.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_api_key_auth_is_unavailable(self):
        write(self.home, self.AUTH, {"OPENAI_API_KEY": "sk-fixture"})
        row = codex.collect(FakeRequest({}), self.home, {})
        self.assertEqual(row["status"], common.UNAVAILABLE)
        self.assertEqual(row["error"], "api-key-auth")

    def test_malformed_auth(self):
        write(self.home, self.AUTH, "{not json")
        self.assertEqual(codex.collect(FakeRequest({}), self.home, {})["error"], "malformed-auth")

    def test_tokens_not_a_dict_is_not_signed_in(self):
        write(self.home, self.AUTH, {"tokens": "nonsense"})
        self.assertEqual(codex.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_malformed_rate_limit_does_not_raise(self):
        self.assertEqual(codex.parse({"rate_limit": "bad"}), [])
        self.assertEqual([m["windowMinutes"] for m in codex.parse(load("codex_usage.json"))], [300, 10080])
        self.assertEqual(codex.parse({"rate_limit": {"primary_window": "bad"}}), [])

    def test_expired_auth(self):
        write(self.home, self.AUTH, {"tokens": {"access_token": make_jwt(PAST_EXP)}})
        request = FakeRequest({"": common.Response(200, {})})
        row = codex.collect(request, self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)
        self.assertEqual(request.calls, [])

    def test_rate_limited(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = codex.collect(FakeRequest({"": common.Response(429, None)}), self.home, {})
        self.assertEqual(row["status"], common.RATE_LIMITED)


if __name__ == "__main__":
    unittest.main()
