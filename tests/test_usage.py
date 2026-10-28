"""Offline collector and transport tests. Every case runs against a fixture
payload and a fake transport; nothing here opens a socket or touches a real
credential file.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from support import FUTURE_EXP, PAST_EXP, ProviderCase, load, make_jwt, write
import usage
from providers import claude, codex, common
import providers as providers_pkg


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
    def test_collector_skips_disabled_providers(self):
        with mock.patch.object(claude, "collect") as disabled, mock.patch.object(codex, "collect", return_value={"provider": "codex"}) as enabled:
            self.assertEqual(usage.collect_all("/unused", {}, select=["codex"]), [{"provider": "codex"}])
            disabled.assert_not_called()
            enabled.assert_called_once()
            enabled.reset_mock()
            self.assertEqual(usage.collect_all("/unused", {}, select=[]), [])
            enabled.assert_not_called()

    def test_collect_all_runs_main_first_then_pool_in_order(self):
        barrier = threading.Barrier(4, timeout=5)
        events = []
        baseline = threading.active_count()

        class Ok:
            NAME, ABBREV = "Ok", "K"

            def __init__(self, provider_id, tag):
                self.ID, self.tag = provider_id, tag

            def collect(self, *args):
                events.append("pool-start")
                barrier.wait()
                return {"provider": self.ID, "tag": self.tag}

        class Main:
            ID, NAME, ABBREV, MAIN_THREAD = "dup", "Main", "M", True

            def collect(self, *args):
                alone = threading.current_thread() is threading.main_thread() and threading.active_count() == baseline
                events.append("main-done")
                return {"provider": self.ID, "alone": alone}

        class Boom:
            ID, NAME, ABBREV = "boom", "Boom", "B"

            def collect(self, *args):
                raise RuntimeError("boom")

        original = providers_pkg.REGISTRY
        providers_pkg.REGISTRY = [Ok("first", "a"), Main(), Ok("dup", "b"), Boom(), Ok("dup", "c"), Ok("last", "d")]
        try:
            rows = usage.collect_all("/nonexistent", {})
        finally:
            providers_pkg.REGISTRY = original
        self.assertEqual(events, ["main-done"] + ["pool-start"] * 4)
        self.assertEqual(rows[0], {"provider": "first", "tag": "a"})
        self.assertEqual(rows[1], {"provider": "dup", "alone": True})
        self.assertEqual(rows[2], {"provider": "dup", "tag": "b"})
        self.assertEqual((rows[3]["provider"], rows[3]["status"], rows[3]["error"]), ("boom", common.ERROR, "internal-error"))
        self.assertEqual(rows[4], {"provider": "dup", "tag": "c"})
        self.assertEqual(rows[5], {"provider": "last", "tag": "d"})
        self.assertTrue(claude.MAIN_THREAD)

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
