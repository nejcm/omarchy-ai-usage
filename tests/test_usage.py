"""Offline provider tests. Every case runs against a fixture payload and a
fake transport; nothing here opens a socket or touches a real credential file.
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import usage  # noqa: E402
from providers import claude, codex, common, cursor, opencode  # noqa: E402
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

    def test_nonfinite_expires_in_rejected(self):
        request = FakeRequest({"": common.Response(200, {"access_token": "new", "expires_in": "Infinity"})})
        fields, error = claude.refresh_access_token(request, "refresh")
        self.assertIsNone(fields)
        self.assertEqual(error, "refresh-failed")

    def test_whole_object_compare_detects_refresh_change(self):
        path = write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "same", "refreshToken": "current"}})
        status = claude.persist_rotation(str(path), {"accessToken": "same", "refreshToken": "old"},
                                         {"access_token": "new"})
        self.assertEqual(status, "changed")

    def test_concurrent_rotation_skip(self):
        path = write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "current-token", "refreshToken": "r"}})
        status = claude.persist_rotation(str(path), {"accessToken": "stale-token"},
                                         {"access_token": "new-token"})
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

    def test_derived_total_when_percentage_absent(self):
        write(self.home, self.AUTH, self.valid_auth())
        routes = {"GetCurrentPeriodUsage": common.Response(200, load("cursor_spend.json"))}
        row = cursor.collect(FakeRequest(routes), self.home, {})
        self.assertEqual(row["status"], common.OK)
        self.assertEqual(row["metrics"][0]["label"], "Total usage")
        self.assertEqual(row["metrics"][0]["percent"], 50.0)

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
        self.assertFalse(os.path.exists(lock.path))

    def test_heartbeat_thread_runs(self):
        lock = claude._RefreshLock(self.lock_path())
        original = claude.LOCK_UPDATE_SECONDS
        claude.LOCK_UPDATE_SECONDS = 0.05
        try:
            self.assertTrue(lock.acquire())
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
        lock = claude._RefreshLock(self.lock_path())
        self.assertTrue(lock.acquire())
        self.assertTrue(os.path.isdir(lock.path))
        lock.release()


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
        self.assertFalse(os.path.exists(str(path.parent / claude.LOCK_NAME)))

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

    def test_huge_expires_in_rejected(self):
        request = FakeRequest({"": common.Response(200, {"access_token": "new", "expires_in": 1e308})})
        fields, error = claude.refresh_access_token(request, "refresh")
        self.assertIsNone(fields)
        self.assertEqual(error, "refresh-failed")

    def test_persist_never_abandons_token_on_absurd_expiry(self):
        path = write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old", "refreshToken": "r"}})
        status = claude.persist_rotation(str(path), {"accessToken": "old", "refreshToken": "r"},
                                         {"access_token": "new", "expires_in": 1e308})
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
        seen = []

        def fake_request(method, url, hosts, headers, body=None, timeout=None, error_body=False):
            seen.append((url, error_body))
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
        self.assertIn(True, [flag for url, flag in seen if "oauth/token" in url])
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
            routes = {
                "api.anthropic.com": common.Response(200, load("claude_usage.json")),
                "chatgpt.com": common.Response(200, load("codex_usage.json")),
                "opencode.ai": common.Response(200, load("opencode_usage.json")),
                "GetCurrentPeriodUsage": common.Response(200, load("cursor_usage.json")),
                "GetPlanInfo": common.Response(200, load("cursor_plan.json")),
            }

            def router(method, url, hosts, headers, body=None, error_body=False):
                host = urlsplit(url).hostname
                return routes.get(host) or routes.get(url.rsplit("/", 1)[-1]) or common.Response(0, None, "network")

            rows = usage.collect_all(home, {}, router)
            self.assertEqual([r["provider"] for r in rows], ["claude", "codex", "opencode", "cursor"])
            self.assertTrue(all(r["status"] == common.OK for r in rows))
            json.dumps({"providers": rows})


if __name__ == "__main__":
    unittest.main()
