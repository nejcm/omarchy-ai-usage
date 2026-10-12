import json
import unittest
from pathlib import Path

from support import FUTURE_EXP, PAST_EXP, FakeRequest, ProviderCase, load, make_jwt, write
from providers import common, grok


class GrokTests(ProviderCase):
    AUTH = ".grok/auth.json"

    def valid_auth(self):
        return {"https://auth.x.ai::client": {"key": make_jwt(FUTURE_EXP), "refresh_token": "r"}}

    def routes(self):
        return {"billing?format=credits": common.Response(200, load("grok_usage.json")),
                "settings": common.Response(200, {"subscription_tier_display": "SuperGrok Heavy"})}

    def test_valid(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest(self.routes())
        row = grok.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(row["plan"], "SuperGrok Heavy")
        self.assertEqual([m["label"] for m in row["metrics"]], ["Weekly", "Pay as you go"])
        self.assertEqual([m["percent"] for m in row["metrics"]], [42.0, 20.0])
        self.assertEqual(row["metrics"][0]["resetsAt"], "2026-07-07T21:36:52Z")
        self.assertEqual(row["metrics"][1]["resetsAt"], "2026-07-07T21:36:52Z")
        self.assertEqual(request.calls[0]["headers"].get("X-XAI-Token-Auth"), "xai-grok-cli")

    def test_non_weekly_period_omits_weekly(self):
        payload = load("grok_usage.json")
        payload["config"]["currentPeriod"]["type"] = "USAGE_PERIOD_TYPE_MONTHLY"
        self.assertEqual([m["label"] for m in grok.parse(payload)], ["Pay as you go"])

    def test_absent_cap_omits_pay_as_you_go(self):
        payload = load("grok_usage.json")
        del payload["config"]["onDemandCap"]
        self.assertEqual([m["label"] for m in grok.parse(payload)], ["Weekly"])

    def test_absent_on_demand_used_is_zero(self):
        payload = load("grok_usage.json")
        del payload["config"]["onDemandUsed"]
        self.assertEqual([m["percent"] for m in grok.parse(payload)], [42.0, 0.0])

    def test_empty_cent_is_zero(self):
        for value in ({}, {"val": None}, {"val": 0}):
            with self.subTest(value=value):
                payload = load("grok_usage.json")
                payload["config"]["onDemandUsed"] = value
                self.assertEqual([m["percent"] for m in grok.parse(payload)], [42.0, 0.0])

    def test_malformed_on_demand_used_is_omitted_not_zero(self):
        for bad in ("bad", True, False):
            with self.subTest(val=bad):
                payload = load("grok_usage.json")
                payload["config"]["onDemandUsed"] = {"val": bad}
                self.assertEqual([m["label"] for m in grok.parse(payload)], ["Weekly"])

    def test_malformed_usage_does_not_raise(self):
        self.assertEqual(grok.parse({"config": "bad"}), [])
        self.assertEqual(grok.parse({"config": {"currentPeriod": "bad"}}), [])
        self.assertEqual(grok.parse({"config": {"onDemandCap": {"val": "bad"},
                                                "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY"}}}), [])
        self.assertEqual(grok.parse({"config": {"onDemandCap": {"val": "bad"}}}), [])

    def test_weekly_period_requires_valid_timestamps(self):
        for period in ({"type": "USAGE_PERIOD_TYPE_WEEKLY"},
                       {"type": "USAGE_PERIOD_TYPE_WEEKLY", "start": "garbage", "end": "2026-07-07T21:36:52Z"},
                       {"type": "USAGE_PERIOD_TYPE_WEEKLY", "start": "2026-07-07T21:36:52Z", "end": "2026-07-01T00:00:00Z"}):
            with self.subTest(period=period):
                self.assertEqual(grok.parse({"config": {"currentPeriod": period}}), [])

    def test_missing_auth(self):
        self.assertEqual(grok.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_malformed_auth(self):
        write(self.home, self.AUTH, "{not json")
        self.assertEqual(grok.collect(FakeRequest({}), self.home, {})["error"], "malformed-auth")

    def test_entry_without_key_is_not_signed_in(self):
        write(self.home, self.AUTH, {"https://auth.x.ai::client": {"refresh_token": "r"}})
        self.assertEqual(grok.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_expired_auth(self):
        write(self.home, self.AUTH, {"https://auth.x.ai::client": {"key": make_jwt(PAST_EXP)}})
        request = FakeRequest(self.routes())
        row = grok.collect(request, self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)
        self.assertEqual(request.calls, [])

    def test_live_later_entry_wins_over_expired_first(self):
        write(self.home, self.AUTH, {"https://auth.x.ai::old": {"key": make_jwt(PAST_EXP)},
                                     "https://auth.x.ai::client": {"key": make_jwt(FUTURE_EXP)}})
        request = FakeRequest(self.routes())
        row = grok.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(request.calls[0]["headers"]["Authorization"], "Bearer " + make_jwt(FUTURE_EXP))

    def test_all_expired_entries_still_expired(self):
        write(self.home, self.AUTH, {"https://auth.x.ai::a": {"key": make_jwt(PAST_EXP)},
                                     "https://auth.x.ai::b": {"key": make_jwt(PAST_EXP - 1)}})
        request = FakeRequest(self.routes())
        row = grok.collect(request, self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)
        self.assertEqual(request.calls, [])

    def test_api_key_scope_is_skipped(self):
        write(self.home, self.AUTH, {"xai::api_key": {"key": "api-key-secret"},
                                     "https://auth.x.ai::client": {"key": make_jwt(FUTURE_EXP)}})
        request = FakeRequest(self.routes())
        row = grok.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(request.calls[0]["headers"]["Authorization"], "Bearer " + make_jwt(FUTURE_EXP))

    def test_api_key_only_is_not_signed_in(self):
        write(self.home, self.AUTH, {"xai::api_key": {"key": "api-key-secret"}})
        request = FakeRequest(self.routes())
        row = grok.collect(request, self.home, {})
        self.assertEqual(row["status"], common.NOT_SIGNED_IN)
        self.assertEqual(request.calls, [])

    def test_sign_in_expired_on_401(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = grok.collect(FakeRequest({"billing?format=credits": common.Response(401, None)}), self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)

    def test_rate_limited(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = grok.collect(FakeRequest({"billing?format=credits": common.Response(429, None)}), self.home, {})
        self.assertEqual(row["status"], common.RATE_LIMITED)

    def test_token_not_in_row(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = grok.collect(FakeRequest(self.routes()), self.home, {})
        self.assertNotIn(make_jwt(FUTURE_EXP), json.dumps(row))

    def test_grok_home_override(self):
        env = {"GROK_HOME": str(Path(self.home) / "grokhome")}
        write(self.home, "grokhome/auth.json", self.valid_auth())
        self.assertEqual(grok.collect(FakeRequest(self.routes()), self.home, env)["status"], common.OK)


    def test_enterprise_oidc_entry_does_not_mask_personal_login(self):
        enterprise, personal = make_jwt(FUTURE_EXP - 5), make_jwt(FUTURE_EXP)
        write(self.home, self.AUTH, {"https://idp.acme.example::client": {"key": enterprise},
                                     "https://auth.x.ai::client": {"key": personal}})
        request = FakeRequest(self.routes())
        row = grok.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(request.calls[0]["headers"]["Authorization"], "Bearer " + personal)

    def test_enterprise_oidc_only_is_not_signed_in(self):
        write(self.home, self.AUTH, {"https://idp.acme.example::client": {"key": make_jwt(FUTURE_EXP)}})
        request = FakeRequest(self.routes())
        row = grok.collect(request, self.home, {})
        self.assertEqual(row["status"], common.NOT_SIGNED_IN)
        self.assertEqual(request.calls, [])

    def test_first_party_issuer_field_is_accepted(self):
        write(self.home, self.AUTH, {"custom::client": {"key": make_jwt(FUTURE_EXP),
                                                        "oidc_issuer": "https://auth.x.ai"}})
        self.assertEqual(grok.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)

    def test_legacy_accounts_scope_is_first_party(self):
        write(self.home, self.AUTH, {"https://accounts.x.ai/sign-in": {"key": make_jwt(FUTURE_EXP)}})
        self.assertEqual(grok.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)


if __name__ == "__main__":
    unittest.main()
