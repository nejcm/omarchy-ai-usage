"""Offline provider tests. Every case runs against a fixture payload and a
fake transport; nothing here opens a socket or touches a real credential file.
"""

from __future__ import annotations

import base64
import io
import http.client
import json
import multiprocessing
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import usage  # noqa: E402
from providers import antigravity, claude, codex, common, cursor, grok, opencode, zai  # noqa: E402
import providers as providers_pkg  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
FUTURE_EXP = 4102444800
PAST_EXP = 1000000000


def load(name):
    return json.loads((FIXTURES / name).read_text())


def jwt(payload):
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_jwt(exp):
    return jwt({"alg": "none"}) + "." + jwt({"exp": exp}) + ".sig"


class FakeRequest:
    """Routes a request to a Response by URL substring; records calls."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, hosts, headers, body=None, error_body=False):
        self.calls.append({"method": method, "url": url, "hosts": tuple(hosts), "headers": dict(headers)})
        for needle, response in self.routes.items():
            if needle in url:
                return response
        return common.Response(0, None, "network")


def write(home, relative, content):
    path = Path(home) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text)
    return path


class ProviderCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def rotation_lock(self, path):
        lock = claude._RefreshLock(str(path.parent / claude.LOCK_NAME))
        self.assertTrue(lock.acquire())
        self.addCleanup(lock.release)
        return lock


class ClaudeTests(ProviderCase):
    AUTH = ".claude/.credentials.json"

    def valid_auth(self):
        return {"claudeAiOauth": {"accessToken": "SECRET-TOKEN", "expiresAt": FUTURE_EXP * 1000,
                                  "refreshToken": "refresh", "rateLimitTier": "default_claude_max_20x"}}

    def test_valid(self):
        write(self.home, self.AUTH, self.valid_auth())
        request = FakeRequest({"oauth/usage": common.Response(200, load("claude_usage.json"))})
        row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual([m["label"] for m in row["metrics"]], ["Session", "Weekly"])
        self.assertEqual([m["percent"] for m in row["metrics"]], [42.0, 18.0])
        self.assertEqual(row["plan"], "Max 20x")
        self.assertEqual(row["resetAt"], "2026-10-11T18:00:00Z")

    def test_missing_auth(self):
        self.assertEqual(claude.collect(FakeRequest({}), self.home, {})["status"], common.NOT_SIGNED_IN)

    def test_malformed_auth(self):
        write(self.home, self.AUTH, "{not json")
        row = claude.collect(FakeRequest({}), self.home, {})
        self.assertEqual(row["status"], common.ERROR)
        self.assertEqual(row["error"], "malformed-auth")

    def test_refresh_success_persists(self):
        write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                                        "expiresAt": PAST_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token",
                                                                    "refresh_token": "new-refresh",
                                                                    "expires_in": 3600}),
                               "oauth/usage": common.Response(200, load("claude_usage.json"))})
        row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        persisted = json.loads((Path(self.home) / self.AUTH).read_text())["claudeAiOauth"]
        self.assertEqual(persisted["accessToken"], "new-token")
        self.assertEqual(persisted["refreshToken"], "new-refresh")
        self.assertGreater(persisted["expiresAt"], PAST_EXP * 1000)
        self.assertNotIn("new-token", json.dumps(row))

    def test_refresh_invalid_grant_is_not_signed_in(self):
        write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                                        "expiresAt": PAST_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(400, {"error": "invalid_grant"})})
        row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.NOT_SIGNED_IN)

    def test_refresh_rejected_is_not_not_signed_in(self):
        write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                                        "expiresAt": PAST_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(400, {"error": "invalid_scope"})})
        row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.ERROR)
        self.assertEqual(row["error"], "refresh-rejected")

    def test_refresh_error_without_body_is_rejected(self):
        write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                                        "expiresAt": PAST_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(401, None)})
        row = claude.collect(request, self.home, {})
        self.assertEqual(row["error"], "refresh-rejected")

    def test_oauth_error_allow_list(self):
        self.assertEqual(claude._oauth_error({"error": "invalid_grant"}), "invalid_grant")
        self.assertEqual(claude._oauth_error({"error": "invalid_scope"}), "invalid_scope")
        self.assertEqual(claude._oauth_error({"error": "something_else"}), "")
        self.assertEqual(claude._oauth_error({"error_description": "invalid_grant"}), "")
        self.assertEqual(claude._oauth_error(None), "")

    def test_refresh_locked_returns_bounded(self):
        path = write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                                              "expiresAt": PAST_EXP * 1000}})
        os.mkdir(str(path.parent / claude.LOCK_NAME))
        request = FakeRequest({"oauth/usage": common.Response(200, load("claude_usage.json"))})
        row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.ERROR)
        self.assertEqual(row["error"], "refresh-locked")
        self.assertEqual(request.calls, [])

    def test_persist_failure_is_error(self):
        write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                                        "expiresAt": PAST_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token",
                                                                    "refresh_token": "new-refresh",
                                                                    "expires_in": 3600}),
                               "oauth/usage": common.Response(200, load("claude_usage.json"))})
        with mock.patch("providers.claude.os.replace", side_effect=OSError("boom")):
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.ERROR)
        self.assertEqual(row["error"], "persist-write-failed")

    def test_nonfinite_expiry_does_not_discard_rotation(self):
        request = FakeRequest({"": common.Response(200, {"access_token": "new", "expires_in": "Infinity"})})
        fields, error = claude.refresh_access_token(request, "refresh")
        self.assertEqual(fields["access_token"], "new")
        self.assertIsNone(error)

    def test_rotation_persists_scopes_and_refresh_expiry(self):
        original = {"accessToken": "old", "refreshToken": "r", "scopes": ["user:inference", "user:plugins"],
                    "refreshTokenExpiresAt": 1}
        path = write(self.home, self.AUTH, {"claudeAiOauth": original})
        self.assertEqual(claude._requested_scopes(original), "user:inference user:plugins")
        self.assertEqual(claude._requested_scopes({}), claude.SCOPES)
        status = claude.persist_rotation(str(path), original,
                                         {"access_token": "new", "refresh_token_expires_in": 3600,
                                          "scope": "user:inference user:profile"},
                                         self.rotation_lock(path))
        self.assertEqual(status, "ok")
        saved = json.loads(path.read_text())["claudeAiOauth"]
        self.assertEqual(saved["scopes"], ["user:inference", "user:profile"])
        self.assertGreater(saved["refreshTokenExpiresAt"], time.time() * 1000)

    def test_whole_object_compare_detects_refresh_change(self):
        path = write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "same", "refreshToken": "current"}})
        status = claude.persist_rotation(str(path), {"accessToken": "same", "refreshToken": "old"},
                                         {"access_token": "new"}, self.rotation_lock(path))
        self.assertEqual(status, "changed")

    def test_concurrent_rotation_skip(self):
        path = write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "current-token", "refreshToken": "r"}})
        status = claude.persist_rotation(str(path), {"accessToken": "stale-token"},
                                         {"access_token": "new-token"}, self.rotation_lock(path))
        self.assertEqual(status, "changed")
        self.assertEqual(json.loads(path.read_text())["claudeAiOauth"]["accessToken"], "current-token")

    def test_invalid_utilization_is_not_zero(self):
        write(self.home, self.AUTH, self.valid_auth())
        payload = {"five_hour": {"utilization": "bad", "resets_at": "2026-10-11T18:00:00Z"}}
        request = FakeRequest({"oauth/usage": common.Response(200, payload)})
        row = claude.collect(request, self.home, {})
        self.assertNotEqual(row["status"], common.OK)
        self.assertEqual(row["metrics"], [])

    def test_malformed_bucket_does_not_raise(self):
        self.assertEqual(claude.parse({"five_hour": "bad"}), [])

    def test_rate_limited(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = claude.collect(FakeRequest({"oauth/usage": common.Response(429, None)}), self.home, {})
        self.assertEqual(row["status"], common.RATE_LIMITED)

    def test_token_not_in_row(self):
        write(self.home, self.AUTH, self.valid_auth())
        row = claude.collect(FakeRequest({"oauth/usage": common.Response(200, load("claude_usage.json"))}),
                             self.home, {})
        self.assertNotIn("SECRET-TOKEN", json.dumps(row))


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
        for value, expected in ((-1, 100.0), (2, 0.0)):
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


class RefreshLockTests(ProviderCase):
    def lock_path(self):
        return os.path.join(self.home, "_lock")

    def test_heartbeat_keeps_lock_fresh(self):
        lock = claude._RefreshLock(self.lock_path())
        self.assertTrue(lock.acquire())
        self.assertTrue(lock._touch())
        self.assertFalse(lock.lost)
        self.assertTrue(lock.still_owned())
        self.assertLessEqual(time.time() - os.stat(lock.path).st_mtime, 5)
        lock.release()
        self.assertTrue(os.path.isdir(lock.path))
        self.assertGreater(time.time() - os.stat(lock.path).st_mtime, claude.LOCK_STALE_SECONDS)

    def test_heartbeat_thread_runs(self):
        lock = claude._RefreshLock(self.lock_path())
        original = claude.LOCK_UPDATE_SECONDS
        claude.LOCK_UPDATE_SECONDS = 0.05
        try:
            self.assertTrue(lock.acquire())
            lock._start_heartbeat()
            time.sleep(0.25)
            self.assertFalse(lock.lost)
            self.assertTrue(lock.still_owned())
            lock.release()
        finally:
            claude.LOCK_UPDATE_SECONDS = original

    def test_lost_ownership_skips_rmdir(self):
        lock = claude._RefreshLock(self.lock_path())
        self.assertTrue(lock.acquire())
        os.rmdir(lock.path)
        os.mkdir(lock.path)
        self.assertFalse(lock.still_owned())
        lock.release()
        self.assertTrue(os.path.isdir(lock.path))

    def test_touch_detects_replacement(self):
        lock = claude._RefreshLock(self.lock_path())
        self.assertTrue(lock.acquire())
        os.rmdir(lock.path)
        os.mkdir(lock.path)
        self.assertFalse(lock._touch())
        self.assertTrue(lock.lost)
        lock.release()
        self.assertTrue(os.path.isdir(lock.path))

    def test_fresh_lock_is_not_stolen(self):
        os.mkdir(self.lock_path())
        lock = claude._RefreshLock(self.lock_path())
        self.assertFalse(lock.acquire())
        self.assertTrue(os.path.isdir(lock.path))

    def test_stale_lock_is_reclaimed(self):
        os.mkdir(self.lock_path())
        old = time.time() - claude.LOCK_STALE_SECONDS - 5
        os.utime(self.lock_path(), (old, old))
        before = os.stat(self.lock_path())
        lock = claude._RefreshLock(self.lock_path())
        self.assertTrue(lock.acquire())
        self.assertNotEqual(os.stat(lock.path).st_ino, before.st_ino)
        lock.release()

    def test_released_lock_can_be_reacquired(self):
        first = claude._RefreshLock(self.lock_path())
        self.assertTrue(first.acquire())
        first.release()
        second = claude._RefreshLock(self.lock_path())
        self.assertTrue(second.acquire())
        second.release()

    def test_stale_lock_file_is_not_removed(self):
        Path(self.lock_path()).write_text("")
        old = time.time() - claude.LOCK_STALE_SECONDS - 5
        os.utime(self.lock_path(), (old, old))
        self.assertFalse(claude._RefreshLock(self.lock_path()).acquire())
        self.assertTrue(os.path.isfile(self.lock_path()))

    def test_concurrent_acquisition_does_not_replace_peer(self):
        lock = claude._RefreshLock(self.lock_path())
        real_publish = claude._publish_lock
        replacement = []

        def publish_after_peer(source, destination):
            os.mkdir(destination)
            replacement.append(os.stat(destination))
            real_publish(source, destination)

        with mock.patch.object(claude, "_publish_lock", side_effect=publish_after_peer):
            self.assertFalse(lock.acquire())
        self.assertIsNone(lock.fd)
        self.assertEqual(os.stat(lock.path).st_ino, replacement[0].st_ino)
        self.assertEqual(os.stat(lock.path).st_mtime_ns, replacement[0].st_mtime_ns)
        self.assertEqual(list(Path(self.home).glob(".oauth-lock.*")), [])

    def test_acquisition_does_not_adopt_replacement(self):
        lock = claude._RefreshLock(self.lock_path())
        real_publish = claude._publish_lock
        replacement = []

        def replace_after_publish(source, destination):
            real_publish(source, destination)
            os.rmdir(destination)
            os.mkdir(destination)
            replacement.append(os.stat(destination))

        with mock.patch.object(claude, "_publish_lock", side_effect=replace_after_publish):
            self.assertFalse(lock.acquire())
        self.assertTrue(lock.lost)
        self.assertIsNone(lock.fd)
        self.assertEqual(os.stat(lock.path).st_mtime_ns, replacement[0].st_mtime_ns)

    def test_release_after_final_stat_never_touches_replacement(self):
        lock = claude._RefreshLock(self.lock_path())
        self.assertTrue(lock.acquire())
        real_owned = lock.still_owned
        replacement = []

        def replace_after_check():
            owned = real_owned()
            os.rmdir(lock.path)
            os.mkdir(lock.path)
            replacement.append(os.stat(lock.path))
            return owned

        with mock.patch.object(lock, "still_owned", side_effect=replace_after_check), \
                mock.patch("providers.claude.os.rmdir", wraps=os.rmdir) as remove:
            lock.release()
        self.assertEqual(remove.call_count, 1)
        self.assertEqual(os.stat(lock.path).st_ino, replacement[0].st_ino)
        self.assertEqual(os.stat(lock.path).st_mtime_ns, replacement[0].st_mtime_ns)

    def test_paused_heartbeat_is_joined_before_release(self):
        lock = claude._RefreshLock(self.lock_path())
        entered, proceed, released = threading.Event(), threading.Event(), threading.Event()
        real_utime = os.utime

        def paused_utime(fd, **kwargs):
            if threading.current_thread() is lock._thread:
                entered.set()
                if not proceed.wait(2):
                    raise AssertionError("heartbeat not resumed")
            return real_utime(fd, **kwargs)

        with mock.patch.object(claude, "LOCK_UPDATE_SECONDS", 0.01), \
                mock.patch("providers.claude.os.utime", side_effect=paused_utime):
            self.assertTrue(lock.acquire())
            lock._start_heartbeat()
            try:
                self.assertTrue(entered.wait(2))
                releaser = threading.Thread(target=lambda: (lock.release(), released.set()))
                releaser.start()
                self.assertFalse(released.wait(0.05))
                os.rmdir(lock.path)
                os.mkdir(lock.path)
                replacement = os.stat(lock.path)
            finally:
                proceed.set()
                releaser.join(2)
                lock.release()
        self.assertTrue(released.is_set())
        self.assertFalse(lock._thread.is_alive())
        self.assertEqual(os.stat(lock.path).st_mtime_ns, replacement.st_mtime_ns)

    def test_replacement_between_stat_and_touch_is_untouched(self):
        lock = claude._RefreshLock(self.lock_path())
        self.assertTrue(lock.acquire())
        self.addCleanup(lock.release)
        real_utime = os.utime
        replacement = []

        def replace_before_touch(fd, **kwargs):
            os.rmdir(lock.path)
            os.mkdir(lock.path)
            replacement.append(os.stat(lock.path))
            return real_utime(fd, **kwargs)

        with mock.patch("providers.claude.os.utime", side_effect=replace_before_touch):
            self.assertFalse(lock._touch())
        self.assertEqual(os.stat(lock.path).st_mtime_ns, replacement[0].st_mtime_ns)


class ClaudeLockFlowTests(ProviderCase):
    AUTH = ".claude/.credentials.json"

    def expired(self):
        return {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                  "expiresAt": PAST_EXP * 1000}}

    def test_lock_lost_aborts_persist_and_keeps_replacement(self):
        path = write(self.home, self.AUTH, self.expired())
        lock_path = str(path.parent / claude.LOCK_NAME)

        def request(method, url, hosts, headers, body=None, timeout=None, error_body=False):
            if "oauth/token" in url:
                os.rmdir(lock_path)
                os.mkdir(lock_path)
                return common.Response(200, {"access_token": "new-token", "expires_in": 3600})
            return common.Response(200, load("claude_usage.json"))

        row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.ERROR)
        self.assertEqual(row["error"], "lock-lost")
        self.assertEqual(json.loads(path.read_text())["claudeAiOauth"]["accessToken"], "old-token")
        self.assertTrue(os.path.isdir(lock_path))

    def test_deadline_exceeded_no_persist(self):
        path = write(self.home, self.AUTH, self.expired())

        def request(method, url, hosts, headers, body=None, timeout=None, error_body=False):
            if "oauth/token" in url:
                time.sleep(0.5)
                return common.Response(200, {"access_token": "new-token", "expires_in": 3600})
            return common.Response(200, load("claude_usage.json"))

        original = claude.TOKEN_DEADLINE_SECONDS
        claude.TOKEN_DEADLINE_SECONDS = 0.1
        try:
            row = claude.collect(request, self.home, {})
        finally:
            claude.TOKEN_DEADLINE_SECONDS = original
        self.assertEqual(row["status"], common.ERROR)
        self.assertEqual(row["error"], "refresh-timeout")
        self.assertEqual(json.loads(path.read_text())["claudeAiOauth"]["accessToken"], "old-token")
        self.assertTrue(os.path.isdir(str(path.parent / claude.LOCK_NAME)))
        self.assertEqual(multiprocessing.active_children(), [])

    def test_http_body_deadline_terminates_and_reaps_exchange(self):
        path = write(self.home, self.AUTH, self.expired())
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        os.write(write_fd, b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n{\"access_token\":")
        client = mock.Mock()
        client.makefile.side_effect = lambda *args: os.fdopen(os.dup(read_fd), "rb")
        marker = Path(self.home) / "exchange-finished"

        def request(*args, **kwargs):
            with http.client.HTTPResponse(client) as response:
                response.begin()
                response.read()
                marker.touch()
                return common.Response(200, {"access_token": "new"})

        started = time.monotonic()
        with mock.patch.object(claude, "TOKEN_DEADLINE_SECONDS", 0.1):
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["error"], "refresh-timeout")
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(multiprocessing.active_children(), [])
        self.assertFalse(marker.exists())
        self.assertEqual(json.loads(path.read_text()), self.expired())

    def test_uninterruptible_exchange_is_killed_before_release(self):
        path = write(self.home, self.AUTH, self.expired())
        worker_pid = Path(self.home) / "worker-pid"
        real_release = claude._RefreshLock.release

        def request(*args, **kwargs):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            worker_pid.write_text(str(os.getpid()))
            time.sleep(10)
            return common.Response(200, {"access_token": "new"})

        def release(lock):
            self.assertEqual(multiprocessing.active_children(), [])
            with self.assertRaises(ProcessLookupError):
                os.kill(int(worker_pid.read_text()), 0)
            real_release(lock)

        with mock.patch.object(claude, "TOKEN_DEADLINE_SECONDS", 0.1), \
                mock.patch.object(claude._RefreshLock, "release", release):
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["error"], "refresh-timeout")
        self.assertEqual(json.loads(path.read_text()), self.expired())

    def test_completed_rotation_at_deadline_is_persisted(self):
        path = write(self.home, self.AUTH, self.expired())
        real_capture = claude._capture

        def capture_then_pause(func, result):
            real_capture(func, result)
            time.sleep(10)

        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token",
                                                                  "refresh_token": "new-refresh"}),
                               "oauth/usage": common.Response(200, load("claude_usage.json"))})
        with mock.patch.object(claude, "TOKEN_DEADLINE_SECONDS", 0.1), \
                mock.patch.object(claude, "_capture", side_effect=capture_then_pause):
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(json.loads(path.read_text())["claudeAiOauth"]["refreshToken"], "new-refresh")
        self.assertEqual(multiprocessing.active_children(), [])

    def test_ownership_loss_during_temp_write_aborts_replace(self):
        path = write(self.home, self.AUTH, self.expired())
        lock_path = path.parent / claude.LOCK_NAME
        successor = {"claudeAiOauth": {"accessToken": "successor", "refreshToken": "successor-refresh"}}
        real_dump = json.dump

        def compromise_while_writing(value, handle):
            real_dump(value, handle)
            os.rmdir(lock_path)
            os.mkdir(lock_path)
            path.write_text(json.dumps(successor))

        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token"})})
        with mock.patch("providers.claude.json.dump", side_effect=compromise_while_writing), \
                mock.patch("providers.claude.os.replace", wraps=os.replace) as replace:
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["error"], "lock-lost")
        replace.assert_not_called()
        self.assertEqual(json.loads(path.read_text()), successor)
        self.assertTrue(lock_path.is_dir())
        self.assertEqual(list(path.parent.glob(".credentials.*.tmp")), [])

    def test_locked_reread_failure_aborts_before_post(self):
        write(self.home, self.AUTH, self.expired())
        calls = []

        def request(method, url, hosts, headers, body=None, timeout=None, error_body=False):
            calls.append(url)
            return common.Response(200, {})

        real = claude._read_oauth
        state = {"count": 0}

        def fake_read(path):
            state["count"] += 1
            return (None, "unreadable") if state["count"] >= 2 else real(path)

        with mock.patch("providers.claude._read_oauth", side_effect=fake_read):
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["error"], "reread-failed")
        self.assertEqual([url for url in calls if "oauth/token" in url], [])

    def test_huge_expiry_does_not_discard_rotation(self):
        request = FakeRequest({"": common.Response(200, {"access_token": "new", "expires_in": 1e308})})
        fields, error = claude.refresh_access_token(request, "refresh")
        self.assertEqual(fields["access_token"], "new")
        self.assertIsNone(error)

    def test_rotation_with_invalid_expiry_is_persisted(self):
        for expires in ("Infinity", 1e308):
            with self.subTest(expires=expires), tempfile.TemporaryDirectory() as home:
                path = write(home, self.AUTH, self.expired())
                request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token",
                                                                          "refresh_token": "new-refresh",
                                                                          "expires_in": expires}),
                                       "oauth/usage": common.Response(200, load("claude_usage.json"))})
                row = claude.collect(request, home, {})
                self.assertEqual(row["status"], common.OK)
                oauth = json.loads(path.read_text())["claudeAiOauth"]
                self.assertEqual(oauth["refreshToken"], "new-refresh")
                self.assertEqual(oauth["expiresAt"], PAST_EXP * 1000)

    def test_persist_never_abandons_token_on_absurd_expiry(self):
        path = write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old", "refreshToken": "r"}})
        status = claude.persist_rotation(str(path), {"accessToken": "old", "refreshToken": "r"},
                                         {"access_token": "new", "expires_in": 1e308}, self.rotation_lock(path))
        self.assertEqual(status, "ok")
        self.assertEqual(json.loads(path.read_text())["claudeAiOauth"]["accessToken"], "new")


class MainEntryTests(ProviderCase):
    def test_refresh_through_main_forwards_error_body(self):
        write(self.home, ".claude/.credentials.json",
              {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                 "expiresAt": PAST_EXP * 1000}})
        routes = {"oauth/token": common.Response(200, {"access_token": "new-token",
                                                       "refresh_token": "new-refresh", "expires_in": 3600}),
                  "oauth/usage": common.Response(200, load("claude_usage.json"))}
        seen = Path(self.home) / "request-flags"

        def fake_request(method, url, hosts, headers, body=None, timeout=None, error_body=False):
            with seen.open("a") as handle:
                handle.write(json.dumps([url, error_body]) + "\n")
            for needle, response in routes.items():
                if needle in url:
                    return response
            return common.Response(0, None, "network")

        with mock.patch("usage.request", side_effect=fake_request), \
                mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = usage.main(["--home", self.home, "--provider", "claude"])

        self.assertEqual(code, 0)
        document = json.loads(out.getvalue())
        self.assertEqual(document["providers"][0]["status"], common.OK)
        self.assertIn(True, [flag for url, flag in map(json.loads, seen.read_text().splitlines()) if "oauth/token" in url])
        persisted = json.loads((Path(self.home) / ".claude/.credentials.json").read_text())
        self.assertEqual(persisted["claudeAiOauth"]["accessToken"], "new-token")


class TransportTests(unittest.TestCase):
    def test_host_allow_list(self):
        response = usage.request("GET", "https://example.com/x", ("api.anthropic.com",), {})
        self.assertEqual(response.status, 0)
        self.assertEqual(response.error, "host-not-allowed")

    def test_header_injection_is_bounded(self):
        response = usage.request("GET", "https://api.anthropic.com/x", ("api.anthropic.com",),
                                 {"Authorization": "Bearer SENTINEL\nInjected"})
        self.assertEqual(response.status, 0)
        self.assertEqual(response.error, "invalid-auth")
        self.assertNotIn("SENTINEL", json.dumps({"error": response.error}))

    def test_redirect_not_followed(self):
        self.assertIsInstance(usage._OPENER, object)
        # A 3xx is surfaced as an HTTP status, never followed.
        self.assertEqual(usage._NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil"), None)


class SharedTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_widget_collection_selection_and_late_output(self):
        source = (ROOT / "Model.js").read_text().replace(".pragma library", "")
        script = source + "\nconst qml = " + json.dumps((ROOT / "BarWidget.qml").read_text()) + ";" + """
const assert = require("node:assert/strict");
const root = {enabledProviders:[], loadedOnce:false, refreshPending:false,
  refreshing:false, lastAttemptMs:0, rows:[], script:"/plugin path/usage.py",
  checkWarnings(rows) { this.warningRows = rows; }};
const process = {running:false};
const Model = {orderedRows, mergeRows, markStale};
function method(name) {
  const start = qml.indexOf("  function " + name + "(");
  const end = qml.indexOf("\\n  }", start) + 4;
  assert(start >= 0 && end > start);
  return new Function("root", "usageProcess", "Model",
    "with (root) { return (" + qml.slice(start, end) + ") }")(root, process, Model);
}
const refresh = method("refresh");
refresh();
assert.equal(process.running, false);
assert.equal(root.loadedOnce, true);
root.enabledProviders = ["cursor", "codex"];
refresh();
assert.deepEqual(process.command, ["python3", "/plugin path/usage.py", "--provider", "cursor", "--provider", "codex"]);
assert.equal(process.running, true);
assert(root.lastAttemptMs > 0);
root.enabledProviders = ["codex"];
refresh();
assert.equal(root.refreshPending, true);
method("applyOutput")(JSON.stringify({providers:[
  {provider:"cursor", status:"ok", metrics:[]},
  {provider:"codex", status:"ok", metrics:[{percent:90}]}]}));
assert.deepEqual(root.rows.map(row => row.provider), ["codex"]);
assert.deepEqual(root.warningRows.map(row => row.provider), ["codex"]);
process.running = false;
refresh();
assert.equal(root.refreshPending, false);
assert.deepEqual(process.command, ["python3", "/plugin path/usage.py", "--provider", "codex"]);
method("applyOutput")("invalid json");
assert.equal(root.rows[0].status, "stale");
"""
        subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_settings_and_warning_periods(self):
        source = (ROOT / "Model.js").read_text().replace(".pragma library", "")
        script = source + """
const assert = require("node:assert/strict");
assert.deepEqual(providerOrder(["cursor", "bad", "cursor"]), ["cursor", "claude", "codex", "opencode", "grok", "antigravity", "zai"]);
assert.deepEqual(providerOrder(null), PROVIDERS);
assert.deepEqual(selectedProviders(PROVIDERS, ["claude"], ["cursor"]), ["codex", "opencode", "grok", "antigravity", "zai"]);
assert.deepEqual(selectedProviders(PROVIDERS, PROVIDERS), []);
assert.deepEqual(selectedProviders(PROVIDERS, {}, {}), PROVIDERS);
const rows = PROVIDERS.map(provider => ({provider, status:"ok", metrics:[{percent:70.4}]}));
assert.deepEqual(orderedRows(rows, ["cursor", "claude"]).map(row => row.provider), ["cursor", "claude"]);
assert.equal(barValue(rows[0], "remaining"), "30%");
assert.equal(barValue(rows[0], "both"), "70% / 30%");
assert.equal(barValue({status:"unavailable"}, "remaining"), "–");
for (const minute of REFRESH_MINUTES) assert.equal(refreshSeconds(minute * 60), minute * 60);
for (const value of [0, -1, "bad", 240, Infinity, null]) assert.equal(refreshSeconds(value), 300);
assert.equal(warningThreshold("bad"), 80);
assert.equal(warningThreshold(0), 1);
assert.equal(warningThreshold(150), 100);
assert.equal(isWarning(rows[0], 70), true);
assert.equal(isWarning({status:"unavailable"}, 80), false);
const row = {provider:"codex", name:"Codex", status:"ok", metrics:[
  {label:"Session", percent:85, resetsAt:"2030-01-01T00:00:00Z"},
  {label:"Weekly", percent:90, resetsAt:"2030-01-07T00:00:00Z"}]};
let result = warningEvents([row], {}, 80, false);
assert.equal(result.events.length, 0);
result = warningEvents([row], result.state, 80, true);
assert.equal(result.events.length, 2);
let state = JSON.parse(JSON.stringify(result.state));
assert.equal(warningEvents([row], state, 80, true).events.length, 0);
row.metrics[0].resetsAt = "2030-01-01T00:00:01.250Z";
assert.equal(warningEvents([row], state, 80, true).events.length, 0);
row.metrics[0].percent = 20;
state = warningEvents([row], state, 80, true).state;
row.metrics[0].percent = 85;
assert.equal(warningEvents([row], state, 80, true).events.length, 0);
row.metrics[0].resetsAt = "2030-01-01T05:00:00Z";
result = warningEvents([row], state, 80, true);
assert.equal(result.events.length, 1);
state = result.state;
row.status = "stale";
row.metrics[1].resetsAt = "2030-01-14T00:00:00Z";
assert.deepEqual(warningEvents([row], state, 80, true), {state, events:[]});
row.status = "ok";
row.metrics = [{label:"Total", percent:85, resetsAt:""}];
result = warningEvents([row], {}, 80, true);
assert.equal(result.events.length, 1);
assert.equal(warningEvents([row], result.state, 80, true).events.length, 0);
row.metrics[0].percent = 79;
state = warningEvents([row], result.state, 80, true).state;
row.metrics[0].percent = 85;
assert.equal(warningEvents([row], state, 80, true).events.length, 1);
row.metrics[0].percent = null;
assert.equal(warningEvents([row], {}, 80, true).events.length, 0);
assert.deepEqual(PROVIDERS, """ + json.dumps([module.ID for module in providers_pkg.REGISTRY]) + ");"
        subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)

    def test_collector_skips_disabled_providers(self):
        with mock.patch.object(claude, "collect") as disabled, mock.patch.object(codex, "collect", return_value={"provider": "codex"}) as enabled:
            self.assertEqual(usage.collect_all("/unused", {}, select=["codex"]), [{"provider": "codex"}])
            disabled.assert_not_called()
            enabled.assert_called_once()
            enabled.reset_mock()
            self.assertEqual(usage.collect_all("/unused", {}, select=[]), [])
            enabled.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_model_usage_formatting_and_colors(self):
        source = (ROOT / "Model.js").read_text().replace(".pragma library", "")
        script = source + """
const assert = require("node:assert/strict");
const row = {status:"ok", metrics:[{percent:18}, {percent:42}]};
assert.equal(barValue(row), "42%");
assert.equal(barValue({status:"unavailable", metrics:[]}), "–");
assert.equal(barValue({status:"ok", metrics:[]}), "–");
assert.equal(barValue({status:"ok", metrics:[{percent:null}, {}]}), "–");
assert.equal(barValue({status:"ok", metrics:[{percent:0}]}), "0%");
for (const [value, color] of [[0,"#4ade80"], [75,"#4ade80"],
  [75.1,"#fb923c"], [90,"#fb923c"], [90.1,"#f87171"], [100,"#f87171"]]) {
  assert.equal(usageColor(value), color);
}
"""
        subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)

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

    def test_jwt_exp_and_non_dict_payload(self):
        self.assertEqual(common.jwt_exp(make_jwt(FUTURE_EXP)), FUTURE_EXP)
        self.assertIsNone(common.jwt_exp("not-a-jwt"))
        self.assertIsNone(common.jwt_exp(jwt({"alg": "none"}) + "." + jwt("scalar") + ".sig"))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_model_merge_keeps_cache_across_failures(self):
        source = (ROOT / "Model.js").read_text().replace(".pragma library", "")
        script = source + """
var rows = [];
rows = mergeRows(rows, [{provider:"x",name:"X",abbrev:"X",status:"ok",plan:"P",
  metrics:[{label:"S",percent:42,resetsAt:""}],resetAt:"",refreshedAt:"t1"}]);
rows = mergeRows(rows, [{provider:"x",name:"X",abbrev:"X",status:"rate-limited",error:"http-429",
  metrics:[],resetAt:"",refreshedAt:"t2"}]);
rows = mergeRows(rows, [{provider:"x",name:"X",abbrev:"X",status:"rate-limited",error:"http-429",
  metrics:[],resetAt:"",refreshedAt:"t3"}]);
console.log(JSON.stringify({rows:rows, marked:markStale(rows)}));
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        for rows in (payload["rows"], payload["marked"]):
            self.assertEqual(rows[0]["status"], "stale")
            self.assertEqual(rows[0]["metrics"][0]["percent"], 42)
            self.assertEqual(rows[0]["refreshedAt"], "t1")

    def test_collect_all_survives_a_broken_provider(self):
        class Boom:
            ID, NAME, ABBREV = "boom", "Boom", "B"

            def collect(self, *args):
                raise RuntimeError("boom")

        original = providers_pkg.REGISTRY
        providers_pkg.REGISTRY = [Boom()]
        try:
            rows = usage.collect_all("/nonexistent", {})
        finally:
            providers_pkg.REGISTRY = original
        self.assertEqual(rows[0]["status"], common.ERROR)
        self.assertEqual(rows[0]["error"], "internal-error")

    def test_collect_all_is_serializable(self):
        with tempfile.TemporaryDirectory() as home:
            write(home, ".claude/.credentials.json",
                  {"claudeAiOauth": {"accessToken": "t", "expiresAt": FUTURE_EXP * 1000}})
            write(home, ".codex/auth.json", {"tokens": {"access_token": make_jwt(FUTURE_EXP)}})
            write(home, ".local/share/opencode/auth.json", {"opencode-go": {"key": "k"}})
            write(home, ".config/cursor/auth.json", {"accessToken": make_jwt(FUTURE_EXP)})
            write(home, ".grok/auth.json", {"https://auth.x.ai::client": {"key": make_jwt(FUTURE_EXP)}})
            write(home, ".gemini/antigravity-cli/antigravity-oauth-token",
                  {"token": {"access_token": "t", "expiry": "2030-01-01T00:00:00Z"}, "auth_method": "consumer"})
            write(home, ".chelper/config.yaml", "api_key: SECRET-KEY\n")
            routes = {
                "api.anthropic.com": common.Response(200, load("claude_usage.json")),
                "chatgpt.com": common.Response(200, load("codex_usage.json")),
                "opencode.ai": common.Response(200, load("opencode_usage.json")),
                "GetCurrentPeriodUsage": common.Response(200, load("cursor_usage.json")),
                "GetPlanInfo": common.Response(200, load("cursor_plan.json")),
                "billing?format=credits": common.Response(200, load("grok_usage.json")),
                "settings": common.Response(200, {"subscription_tier_display": "SuperGrok Heavy"}),
                "cloudcode-pa.googleapis.com": common.Response(200, load("antigravity_usage.json")),
                "api.z.ai": common.Response(200, load("zai_quota.json")),
            }

            def router(method, url, hosts, headers, body=None, error_body=False):
                host = urlsplit(url).hostname
                return routes.get(host) or routes.get(url.rsplit("/", 1)[-1]) or common.Response(0, None, "network")

            rows = usage.collect_all(home, {}, router)
            self.assertEqual([r["provider"] for r in rows], ["claude", "codex", "opencode", "cursor", "grok", "antigravity", "zai"])
            self.assertTrue(all(r["status"] == common.OK for r in rows))
            json.dumps({"providers": rows})


if __name__ == "__main__":
    unittest.main()
