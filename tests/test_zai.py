import json
import unittest
from pathlib import Path

from support import FakeRequest, ProviderCase, load, write
from providers import common, zai


class ZaiTests(ProviderCase):
    AUTH = ".chelper/config.yaml"

    def valid_auth(self):
        return "plan: glm_coding_plan_global\napi_key: SECRET-KEY\n"

    def routes(self):
        return {"quota/limit": common.Response(200, load("zai_quota.json")),
                "subscription/list": common.Response(200, load("zai_subscription.json"))}

    def test_valid(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest(self.routes())
        row = zai.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(row["plan"], "GLM Coding Max")
        self.assertEqual([m["label"] for m in row["metrics"]], ["Session", "Weekly", "Web searches"])
        self.assertEqual([m["percent"] for m in row["metrics"]], [25.0, 42.0, 1.0])
        self.assertEqual(row["metrics"][0]["resetsAt"], "2026-01-01T00:00:00Z")
        self.assertEqual(request.calls[0]["headers"]["Authorization"], "Bearer SECRET-KEY")

    def test_missing_key(self):
        self.assertEqual(zai.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_quoted_key(self):
        write(self.home, self.AUTH, 'api_key: "SECRET-KEY"\n')
        self.assertEqual(zai.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)

    def test_revoked_key_is_not_signed_in(self):
        write(self.home, self.AUTH, "plan: glm_coding_plan_global\napi_key: null\n")
        self.assertEqual(zai.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_inline_comment_on_null_falls_back(self):
        write(self.home, self.AUTH, "api_key: null # signed out\n")
        write(self.home, ".claude/settings.json", {"env": {
            "ANTHROPIC_AUTH_TOKEN": "SECRET-KEY", "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"}})
        self.assertEqual(zai.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)

    def test_tab_before_comment_is_not_a_key(self):
        write(self.home, self.AUTH, "api_key: null\t# signed out\n")
        self.assertEqual(zai.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_comment_only_value_is_not_a_key(self):
        write(self.home, self.AUTH, "api_key: # signed out\n")
        self.assertEqual(zai.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_inline_comment_is_stripped(self):
        write(self.home, self.AUTH, "api_key: SECRET-KEY # note\n")
        request = FakeRequest(self.routes())
        self.assertEqual(zai.collect(request, self.home, {})["status"], common.OK)
        self.assertEqual(request.calls[0]["headers"]["Authorization"], "Bearer SECRET-KEY")

    def test_hash_inside_quotes_is_kept(self):
        write(self.home, self.AUTH, 'api_key: "SEC#RET"\n')
        request = FakeRequest(self.routes())
        self.assertEqual(zai.collect(request, self.home, {})["status"], common.OK)
        self.assertEqual(request.calls[0]["headers"]["Authorization"], "Bearer SEC#RET")

    def test_unreadable_config_falls_back(self):
        path = Path(self.home) / self.AUTH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"api_key: \xff\xfe\n")
        write(self.home, ".claude/settings.json", {"env": {
            "ANTHROPIC_AUTH_TOKEN": "SECRET-KEY", "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"}})
        self.assertEqual(zai.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)

    def test_unreadable_config_without_fallback_is_not_signed_in(self):
        path = Path(self.home) / self.AUTH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe")
        self.assertEqual(zai.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_keyless_cli_file_falls_back_to_claude_settings(self):
        write(self.home, self.AUTH, "lang: en_US\n")
        write(self.home, ".claude/settings.json", {"env": {
            "ANTHROPIC_AUTH_TOKEN": "SECRET-KEY", "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"}})
        self.assertEqual(zai.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)

    def test_malformed_claude_settings_is_error(self):
        write(self.home, ".claude/settings.json", "{not json")
        self.assertEqual(zai.collect(FakeRequest({}), self.home, {})["error"], "malformed-auth")

    def test_claude_settings_fallback(self):
        write(self.home, ".claude/settings.json", {"env": {
            "ANTHROPIC_AUTH_TOKEN": "SECRET-KEY", "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"}})
        self.assertEqual(zai.collect(FakeRequest(self.routes()), self.home, {})["status"], common.OK)

    def test_claude_settings_ignored_for_other_base_url(self):
        write(self.home, ".claude/settings.json", {"env": {
            "ANTHROPIC_AUTH_TOKEN": "anthropic-token", "ANTHROPIC_BASE_URL": "https://api.anthropic.com"}})
        request = FakeRequest(self.routes())
        row = zai.collect(request, self.home, {})
        self.assertEqual(row["status"], common.NOT_SIGNED_IN)
        self.assertEqual(request.calls, [])

    def test_token_not_in_row(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = zai.collect(FakeRequest(self.routes()), self.home, {})
        self.assertNotIn("SECRET-KEY", json.dumps(row))

    def test_malformed_usage_does_not_raise(self):
        self.assertEqual(zai.parse({"data": "bad"}), [])
        self.assertEqual(zai.parse({"data": {"limits": "bad"}}), [])
        self.assertEqual(zai.parse({"data": {"limits": [None, "x"]}}), [])

    def test_unknown_unit_ignored(self):
        payload = load("zai_quota.json")
        payload["data"]["limits"][0] = {"type": "CREDIT_LIMIT", "unit": 99, "number": 1, "percentage": 70}
        self.assertEqual([m["label"] for m in zai.parse(payload)], ["Weekly", "Web searches"])

    def test_missing_percentage_is_omitted_not_zero(self):
        payload = {"data": {"limits": [{"type": "TOKENS_LIMIT", "unit": 3, "number": 5}]}}
        self.assertEqual(zai.parse(payload), [])

    def test_daily_window_is_weekly(self):
        payload = {"data": {"limits": [
            {"type": "TOKENS_LIMIT", "unit": 4, "number": 1, "percentage": 60, "nextResetTime": 1767225600000}]}}
        self.assertEqual([m["label"] for m in zai.parse(payload)], ["Weekly"])

    def test_web_searches_requires_positive_limit(self):
        payload = {"data": {"limits": [{"type": "TIME_LIMIT", "unit": 5, "number": 1, "usage": 0, "currentValue": 0}]}}
        self.assertEqual(zai.parse(payload), [])

    def test_root_level_limits(self):
        payload = {"success": True, "limits": [{"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 25}]}
        self.assertEqual([m["label"] for m in zai.parse(payload)], ["Session"])

    def test_no_coding_plan(self):
        write(self.home, self.AUTH, self.valid_auth())
        response = common.Response(200, {"success": False, "code": 500, "msg": "No GLM Coding Plan"})
        row = zai.collect(FakeRequest({"quota/limit": response}), self.home, {})
        self.assertEqual(row["status"], common.UNAVAILABLE)
        self.assertEqual(row["error"], "no-coding-plan")

    def test_empty_limits_is_unavailable(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = zai.collect(FakeRequest({"quota/limit": common.Response(200, {"success": True, "data": {"limits": []}})}),
                          self.home, {})
        self.assertEqual(row["status"], common.UNAVAILABLE)

    def test_plan_failure_keeps_metrics(self):
        write(self.home, self.AUTH, self.valid_auth())
        routes = {"quota/limit": common.Response(200, load("zai_quota.json")),
                  "subscription/list": common.Response(500, None)}
        row = zai.collect(FakeRequest(routes), self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(row["plan"], "")

    def test_invalid_key_on_403(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = zai.collect(FakeRequest({"quota/limit": common.Response(403, None)}), self.home, {})
        self.assertEqual(row["status"], common.EXPIRED)

    def test_rate_limited(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = zai.collect(FakeRequest({"quota/limit": common.Response(429, None)}), self.home, {})
        self.assertEqual(row["status"], common.RATE_LIMITED)

    def test_claude_config_dir_override(self):
        env = {"CLAUDE_CONFIG_DIR": str(Path(self.home) / "cc")}
        write(self.home, "cc/settings.json", {"env": {
            "ANTHROPIC_AUTH_TOKEN": "SECRET-KEY", "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"}})
        self.assertEqual(zai.collect(FakeRequest(self.routes()), self.home, env)["status"], common.OK)


if __name__ == "__main__":
    unittest.main()
