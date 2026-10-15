from __future__ import annotations

import http.client
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from support import FUTURE_EXP, PAST_EXP, ROOT, FakeRequest, ProviderCase, load, write
import usage
from providers import claude, common


class ClaudeTests(ProviderCase):
    AUTH = ".claude/.credentials.json"

    def valid_auth(self):
        return {"claudeAiOauth": {"accessToken": "SECRET-TOKEN", "expiresAt": FUTURE_EXP * 1000,
                                  "refreshToken": "refresh", "rateLimitTier": "default_claude_max_20x"}}

    def collect_counting_exchanges(self, request):
        """Collect with exchanges counted in-process; the token call itself forks."""
        real_refresh = claude.refresh_access_token
        exchanges = []

        def refresh(*args, **kwargs):
            exchanges.append(args)
            return real_refresh(*args, **kwargs)

        with mock.patch("providers.claude.refresh_access_token", side_effect=refresh):
            row = claude.collect(request, self.home, {})
        return row, exchanges

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

    def test_usage_401_on_valid_token_refreshes_then_retries(self):
        write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "refresh",
                                                       "expiresAt": FUTURE_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token",
                                                                    "refresh_token": "new-refresh",
                                                                    "expires_in": 3600}),
                               "oauth/usage": [common.Response(401, None),
                                               common.Response(200, load("claude_usage.json"))]})
        row, exchanges = self.collect_counting_exchanges(request)
        self.assertEqual(row["status"], common.OK)
        usage = [call for call in request.calls if "oauth/usage" in call["url"]]
        self.assertEqual([call["headers"]["Authorization"] for call in usage],
                         ["Bearer old-token", "Bearer new-token"])
        self.assertEqual(len(exchanges), 1)

    def test_usage_401_kept_when_refresh_fails(self):
        write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "refresh",
                                                       "expiresAt": FUTURE_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(500, None),
                               "oauth/usage": common.Response(401, None)})
        row, exchanges = self.collect_counting_exchanges(request)
        self.assertEqual(row["status"], common.EXPIRED)
        self.assertEqual(row["error"], "http-401")
        self.assertEqual(len(exchanges), 1)
        self.assertEqual(len([call for call in request.calls if "oauth/usage" in call["url"]]), 1)

    def test_usage_401_after_expiry_refresh_does_not_refresh_again(self):
        write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                                       "expiresAt": PAST_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token",
                                                                    "expires_in": 3600}),
                               "oauth/usage": common.Response(401, None)})
        row, exchanges = self.collect_counting_exchanges(request)
        self.assertEqual(row["status"], common.EXPIRED)
        self.assertEqual(row["error"], "http-401")
        self.assertEqual(len(exchanges), 1)
        usage = [call for call in request.calls if "oauth/usage" in call["url"]]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["headers"]["Authorization"], "Bearer new-token")

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
        path = write(self.home, self.AUTH, {"claudeAiOauth": {"accessToken": "old-token", "refreshToken": "old-refresh",
                                                              "expiresAt": PAST_EXP * 1000}})
        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token",
                                                                    "refresh_token": "new-refresh",
                                                                    "expires_in": 3600})})
        with mock.patch("providers.claude.os.replace", side_effect=OSError("boom")):
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["error"], "persist-write-failed")
        self.assertEqual(json.loads(path.read_text())["claudeAiOauth"]["accessToken"], "old-token")

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
                                          "scope": "user:inference user:profile"})
        self.assertEqual(status, "ok")
        saved = json.loads(path.read_text())["claudeAiOauth"]
        self.assertEqual(saved["scopes"], ["user:inference", "user:profile"])
        self.assertGreater(saved["refreshTokenExpiresAt"], time.time() * 1000)

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
        with mock.patch.object(claude, "LOCK_UPDATE_SECONDS", 0.05):
            self.assertTrue(lock.acquire())
            lock._start_heartbeat()
            time.sleep(0.25)
            self.assertFalse(lock.lost)
            self.assertTrue(lock.still_owned())
            lock.release()

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

    def test_lock_lost_during_exchange_still_persists_rotation(self):
        path = write(self.home, self.AUTH, self.expired())
        lock_path = str(path.parent / claude.LOCK_NAME)

        def request(method, url, hosts, headers, body=None, timeout=None, error_body=False):
            if "oauth/token" in url:
                os.rmdir(lock_path)
                os.mkdir(lock_path)
                return common.Response(200, {"access_token": "new-token", "refresh_token": "new-refresh",
                                             "expires_in": 3600})
            return common.Response(200, load("claude_usage.json"))

        row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        saved = json.loads(path.read_text())["claudeAiOauth"]
        self.assertEqual(saved["accessToken"], "new-token")
        self.assertEqual(saved["refreshToken"], "new-refresh")
        self.assertTrue(os.path.isdir(lock_path))

    def test_lock_lost_after_exchange_still_persists_rotation(self):
        path = write(self.home, self.AUTH, self.expired())
        lock_path = path.parent / claude.LOCK_NAME
        real_refresh = claude.refresh_access_token

        def refresh_then_lose_lock(request, refresh_token, lock=None, scopes=None):
            fields, error = real_refresh(request, refresh_token, lock, scopes)
            os.rmdir(lock_path)
            os.mkdir(lock_path)
            return fields, error

        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token",
                                                                    "refresh_token": "new-refresh",
                                                                    "expires_in": 3600}),
                               "oauth/usage": common.Response(200, load("claude_usage.json"))})
        with mock.patch("providers.claude.refresh_access_token", side_effect=refresh_then_lose_lock):
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        saved = json.loads(path.read_text())["claudeAiOauth"]
        self.assertEqual(saved["accessToken"], "new-token")
        self.assertEqual(saved["refreshToken"], "new-refresh")
        self.assertTrue(lock_path.is_dir())
        usage = [call for call in request.calls if "oauth/usage" in call["url"]]
        self.assertEqual(usage[0]["headers"]["Authorization"], "Bearer new-token")

    def test_deadline_exceeded_no_persist(self):
        path = write(self.home, self.AUTH, self.expired())

        def request(method, url, hosts, headers, body=None, timeout=None, error_body=False):
            if "oauth/token" in url:
                time.sleep(0.5)
                return common.Response(200, {"access_token": "new-token", "expires_in": 3600})
            return common.Response(200, load("claude_usage.json"))

        with mock.patch.object(claude, "TOKEN_DEADLINE_SECONDS", 0.1):
            row = claude.collect(request, self.home, {})
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

    def test_sigterm_during_exchange_persists_rotation(self):
        path = write(self.home, self.AUTH, self.expired())
        marker = Path(self.home) / "exchange-started"
        proceed = Path(self.home) / "exchange-proceed"
        script = """
import json, os, sys, time
from providers import claude, common

path, marker, proceed = sys.argv[1:4]

def request(method, url, hosts, headers, body=None, timeout=None, error_body=False):
    open(marker, "w").close()
    deadline = time.monotonic() + 5
    while not os.path.exists(proceed) and time.monotonic() < deadline:
        time.sleep(0.01)
    return common.Response(200, {"access_token": "new-token",
                                 "refresh_token": "new-refresh", "expires_in": 3600})

with open(path) as handle:
    original = json.load(handle)["claudeAiOauth"]
claude._refresh_locked(request, path, original, "old-refresh")
"""
        process = subprocess.Popen([sys.executable, "-c", script, str(path), str(marker), str(proceed)],
                                   env={**os.environ, "PYTHONPATH": str(ROOT)})
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(marker.exists(), "exchange never started")
        process.send_signal(signal.SIGTERM)
        proceed.touch()
        self.assertEqual(process.wait(timeout=10), -signal.SIGTERM)
        saved = json.loads(path.read_text())["claudeAiOauth"]
        self.assertEqual(saved["accessToken"], "new-token")
        self.assertEqual(saved["refreshToken"], "new-refresh")

    def test_successor_write_during_temp_write_is_preserved(self):
        path = write(self.home, self.AUTH, self.expired())
        lock_path = path.parent / claude.LOCK_NAME
        successor = {"accessToken": "successor", "refreshToken": "successor-refresh"}
        real_dump = json.dump

        def compromise_while_writing(value, handle):
            real_dump(value, handle)
            os.rmdir(lock_path)
            os.mkdir(lock_path)
            path.write_text(json.dumps({"claudeAiOauth": successor}))

        request = FakeRequest({"oauth/token": common.Response(200, {"access_token": "new-token"}),
                               "oauth/usage": common.Response(200, load("claude_usage.json"))})
        with mock.patch("providers.claude.json.dump", side_effect=compromise_while_writing), \
                mock.patch("providers.claude.os.replace", wraps=os.replace) as replace:
            row = claude.collect(request, self.home, {})
        self.assertEqual(row["status"], common.OK)
        replace.assert_not_called()
        self.assertEqual(json.loads(path.read_text())["claudeAiOauth"], successor)
        self.assertTrue(lock_path.is_dir())
        self.assertEqual(list(path.parent.glob(".credentials.*.tmp")), [])
        usage = [call for call in request.calls if "oauth/usage" in call["url"]]
        self.assertEqual(usage[0]["headers"]["Authorization"], "Bearer successor")

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
                                         {"access_token": "new", "expires_in": 1e308})
        self.assertEqual(status, "ok")
        self.assertEqual(json.loads(path.read_text())["claudeAiOauth"]["accessToken"], "new")


if __name__ == "__main__":
    unittest.main()
