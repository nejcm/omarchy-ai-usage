"""Claude Code usage, refreshing its OAuth token under the CLI's own lock."""

from __future__ import annotations

import ctypes
import json
import math
import multiprocessing
import os
import re
import signal
import tempfile
import threading
import time

from . import common

ID = "claude"
NAME = "Claude Code"
ABBREV = "C"
PROVIDER = (ID, NAME, ABBREV)
HOSTS = ("api.anthropic.com", "platform.claude.com")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
LOCK_NAME = ".oauth_refresh.lock"
LOCK_STALE_SECONDS = 60
LOCK_UPDATE_SECONDS = 5
TOKEN_DEADLINE_SECONDS = 20
MAX_EXPIRY_SECONDS = 365 * 24 * 60 * 60
OAUTH_ERRORS = {"invalid_grant", "invalid_scope", "invalid_client",
                "invalid_request", "unauthorized_client", "unsupported_grant_type"}
_renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
_renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
_renameat2.restype = ctypes.c_int


def _publish_lock(source, destination):
    # RENAME_NOREPLACE publishes the known inode without replacing another owner.
    if _renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        raise OSError(ctypes.get_errno(), "lock-publish-failed")


def credentials_path(home: str, env: dict) -> str:
    return os.path.join(common.claude_config_directory(home, env.get("CLAUDE_CONFIG_DIR")), ".credentials.json")


def _read_oauth(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return None, "unreadable"
    oauth = document.get("claudeAiOauth") if isinstance(document, dict) else None
    if not isinstance(oauth, dict):
        return None, "unreadable"
    return oauth, None


def read_credentials(home: str, env: dict):
    """Return (oauth, error code, path); oauth is the claudeAiOauth mapping."""
    path = credentials_path(home, env)
    oauth, error = _read_oauth(path)
    if error == "unreadable":
        if not os.path.exists(path):
            return None, common.NOT_SIGNED_IN, path
        return None, "malformed-auth", path
    if not str(oauth.get("accessToken") or "").strip():
        return None, common.NOT_SIGNED_IN, path
    return oauth, None, path


def plan_label(oauth: dict) -> str:
    tier = str(oauth.get("rateLimitTier") or "")
    match = re.search(r"max_(\d+x)", tier, re.IGNORECASE)
    if match:
        return "Max " + match.group(1)
    subscription = str(oauth.get("subscriptionType") or "")
    return subscription[:1].upper() + subscription[1:] if subscription else ""


def parse(payload: dict) -> list:
    metrics = []
    for key, label, minutes in (("five_hour", "Session", 5 * 60), ("seven_day", "Weekly", 7 * 24 * 60)):
        bucket = payload.get(key)
        if not isinstance(bucket, dict):
            continue
        metric = common.metric(label, common.percent(bucket.get("utilization")),
                               common.reset_iso(bucket.get("resets_at")), minutes)
        if metric:
            metrics.append(metric)
    for limit in payload.get("limits") or []:
        if not isinstance(limit, dict) or limit.get("kind") != "weekly_scoped":
            continue
        model = ((limit.get("scope") or {}).get("model") or {}).get("display_name")
        if not model:
            continue
        metric = common.metric(f"{model} weekly", common.percent(limit.get("percent")),
                               common.reset_iso(limit.get("resets_at")), 7 * 24 * 60)
        if metric:
            metrics.append(metric)
    return metrics


# Stale reclaim mirrors Claude Code's proper-lockfile; its pathname rmdir is equally unfenced.
class _RefreshLock:

    def __init__(self, path: str):
        self.path = path
        self.held = False
        self.lost = False
        self.inode = -1
        self.mtime_ns = None
        self.fd = None
        self._mutex = threading.RLock()
        self._stop = None
        self._thread = None

    def _reclaim_stale(self) -> bool:
        try:
            stat = os.lstat(self.path)
            if not os.path.isdir(self.path) or os.path.islink(self.path):
                return False
            if time.time_ns() - stat.st_mtime_ns <= LOCK_STALE_SECONDS * 1_000_000_000:
                return False
            os.rmdir(self.path)
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True

    def acquire(self) -> bool:
        if os.path.lexists(self.path) and not self._reclaim_stale():
            return False
        private = None
        try:
            private = tempfile.mkdtemp(dir=os.path.dirname(self.path) or ".", prefix=".oauth-lock.")
            self.fd = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stat = os.fstat(self.fd)
            _publish_lock(private, self.path)
            private = None
        except OSError:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            return False
        finally:
            if private is not None:
                os.rmdir(private)
        self.inode = (stat.st_dev, stat.st_ino)
        self.mtime_ns = stat.st_mtime_ns
        self.held = True
        self.lost = False
        self._stop = threading.Event()
        if not self.still_owned():
            self.release()
            return False
        return True

    def _start_heartbeat(self) -> None:
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def _heartbeat(self) -> None:
        while not self._stop.wait(LOCK_UPDATE_SECONDS):
            if not self._touch():
                return

    def _touch(self) -> bool:
        with self._mutex:
            if not self.still_owned():
                return False
            now_ns = time.time_ns()
            try:
                os.utime(self.fd, ns=(now_ns, now_ns))
                self.mtime_ns = os.fstat(self.fd).st_mtime_ns
            except OSError:
                self.lost = True
                return False
            return self.still_owned()

    def still_owned(self) -> bool:
        with self._mutex:
            if self.lost or not self.held:
                return False
            try:
                stat = os.stat(self.path, follow_symlinks=False)
                owned = ((stat.st_dev, stat.st_ino) == self.inode
                         and stat.st_mtime_ns == self.mtime_ns)
            except OSError:
                owned = False
            self.lost = not owned
            return owned

    def release(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._mutex:
            try:
                if self.still_owned():
                    stale_ns = time.time_ns() - (LOCK_STALE_SECONDS + 1) * 1_000_000_000
                    os.utime(self.fd, ns=(stale_ns, stale_ns))
            except OSError:
                self.lost = True
            finally:
                self.held = False
                if self.fd is not None:
                    os.close(self.fd)
                    self.fd = None


def _oauth_error(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        error = error.get("type") or error.get("error")
    return error if isinstance(error, str) and error in OAUTH_ERRORS else ""


def _finite_seconds(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and 0 < seconds <= MAX_EXPIRY_SECONDS else None


def _bounded_call(func, deadline_seconds, lock):
    with os.fdopen(os.memfd_create("oauth-response", os.MFD_CLOEXEC), "w+b") as result:
        process = multiprocessing.get_context("fork").Process(target=_capture, args=(func, result))
        try:
            process.start()
            if lock is not None:
                lock._start_heartbeat()
            process.join(deadline_seconds)
            if process.is_alive():
                process.terminate()
                process.join(1)
        finally:
            if process.pid is not None:
                if process.is_alive():
                    process.kill()
                process.join()
                process.close()
        result.seek(0)
        try:
            value = json.load(result)
        except ValueError:
            return None
        if value == "timeout":
            return None
        if value is None:
            raise RuntimeError("exchange-failed")
        return common.Response(value["status"], value["data"], value["error"])


class _ExchangeTimeout(BaseException):
    pass


def _interrupt_exchange(signum, frame):
    while frame is not None:
        if frame.f_code is _capture.__code__ and frame.f_locals.get("response") is not None:
            return
        frame = frame.f_back
    raise _ExchangeTimeout


def _capture(func, result):
    response = None
    timed_out = False
    signal.signal(signal.SIGTERM, _interrupt_exchange)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})
    try:
        response = func()
    except _ExchangeTimeout:
        timed_out = True
    except BaseException:
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        value = "timeout" if timed_out else None
        if response is not None:
            value = {"status": response.status, "data": response.data, "error": response.error}
        result.write(json.dumps(value).encode("utf-8"))
        result.flush()


def refresh_access_token(request, refresh_token: str, lock=None, scopes: str = SCOPES):
    """Exchange a refresh token; (fields, None) on success, else (None, code)."""
    if not refresh_token:
        return None, "no-refresh-token"
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "scope": scopes,
    }).encode("utf-8")

    def exchange():
        return request("POST", TOKEN_URL, HOSTS, {"Content-Type": "application/json"},
                       body=body, error_body=True)

    try:
        response = _bounded_call(exchange, TOKEN_DEADLINE_SECONDS, lock)
    except Exception:
        return None, "refresh-failed"
    if response is None:
        return None, "refresh-timeout"
    if response.status in (400, 401):
        if _oauth_error(response.data) == "invalid_grant":
            return None, "invalid_grant"
        return None, "refresh-rejected"
    if response.status != 200 or not isinstance(response.data, dict):
        return None, "refresh-failed"
    token = str(response.data.get("access_token") or "").strip()
    if not token:
        return None, "refresh-failed"
    return response.data, None


def _expiry_ms(seconds):
    if seconds is None:
        return None
    try:
        return int(time.time() * 1000) + int(seconds * 1000)
    except (OverflowError, ValueError):
        return None


def _apply_rotation(oauth: dict, rotated: dict) -> dict:
    """Merge token-endpoint fields into a credentials mapping, as the CLI stores them."""
    oauth = dict(oauth)
    oauth["accessToken"] = str(rotated["access_token"]).strip()
    if str(rotated.get("refresh_token") or "").strip():
        oauth["refreshToken"] = str(rotated["refresh_token"]).strip()
    expiry = _expiry_ms(_finite_seconds(rotated.get("expires_in")))
    if expiry is not None:
        oauth["expiresAt"] = expiry
    refresh_expiry = _expiry_ms(_finite_seconds(rotated.get("refresh_token_expires_in")))
    if refresh_expiry is not None:
        oauth["refreshTokenExpiresAt"] = refresh_expiry
    scope = rotated.get("scope")
    if isinstance(scope, str) and scope.split():
        oauth["scopes"] = scope.split()
    return oauth


def _requested_scopes(oauth: dict) -> str:
    scopes = oauth.get("scopes")
    if isinstance(scopes, list) and scopes and all(isinstance(item, str) and item.strip() for item in scopes):
        return " ".join(scopes)
    return SCOPES


def persist_rotation(path: str, original: dict, rotated: dict) -> str:
    """Atomically write rotated tokens when the credentials still match the exchange."""
    access = str(rotated.get("access_token") or "").strip()
    if not access:
        return "write-failed"
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return "unreadable"
    if not isinstance(document, dict):
        return "unreadable"
    current = document.get("claudeAiOauth")
    if not isinstance(current, dict):
        return "unreadable"
    if current != original:
        return "changed"

    updated = dict(document, claudeAiOauth=_apply_rotation(current, rotated))

    directory = os.path.dirname(path) or "."
    try:
        handle_fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".credentials.", suffix=".tmp")
    except OSError:
        return "write-failed"
    try:
        os.fchmod(handle_fd, 0o600)
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(updated, handle)
        latest, error = _read_oauth(path)
        if error or latest != original:
            return "changed"
        os.replace(tmp_path, path)
    except OSError:
        return "write-failed"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return "ok"


def _refresh_locked(request, path: str, original: dict, refresh_token: str):
    lock = _RefreshLock(os.path.join(os.path.dirname(path) or ".", LOCK_NAME))
    # SIGTERM stays pending until the rotation is persisted and the lock released.
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        if not lock.acquire():
            return None, "refresh-locked"
        try:
            current, error = _read_oauth(path)
            if error:
                return None, "reread-failed"
            if current != original:
                return current, None
            if not lock.still_owned():
                return None, "lock-lost"
            fields, error = refresh_access_token(request, refresh_token, lock, _requested_scopes(original))
            if error:
                return None, error
            status = persist_rotation(path, original, fields)
            if status == "changed":
                current, _ = _read_oauth(path)
                if current is not None:
                    return current, None
                return None, "persist-changed"
            if status != "ok":
                return None, "persist-" + status
            return _apply_rotation(original, fields), None
        finally:
            lock.release()
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _refresh_result(error, plan: str):
    if error == "invalid_grant":
        return common.row(PROVIDER, common.NOT_SIGNED_IN, plan=plan, error="invalid-grant")
    if error == "no-refresh-token":
        return common.row(PROVIDER, common.EXPIRED, plan=plan, error="auth-expired")
    if error and error != "refresh-failed":
        return common.error_row(PROVIDER, error, plan)
    return None


def _usage(request, token: str):
    return request("GET", USAGE_URL, HOSTS, {
        "Authorization": "Bearer " + token,
        "anthropic-beta": "oauth-2025-04-20",
    })


def _live_plan(request, token: str, fallback: str) -> str:
    """Credentials cache the plan from login, so an upgrade only shows in the profile."""
    response = request("GET", PROFILE_URL, HOSTS, {
        "Authorization": "Bearer " + token,
        "anthropic-beta": "oauth-2025-04-20",
    })
    organization = response.data.get("organization") if response.status == 200 and isinstance(response.data, dict) else None
    if not isinstance(organization, dict):
        return fallback
    kind = str(organization.get("organization_type") or "").removeprefix("claude_")
    return plan_label({"rateLimitTier": organization.get("rate_limit_tier"), "subscriptionType": kind}) or fallback


def collect(request, home: str, env: dict) -> dict:
    oauth, code, path = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(PROVIDER, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(PROVIDER, code)

    plan = plan_label(oauth)
    refresh_token = str(oauth.get("refreshToken") or "").strip()
    token = str(oauth.get("accessToken")).strip()
    expired = common.is_expired_ms(oauth.get("expiresAt"))

    response = None if expired else _usage(request, token)
    if expired or response.status == 401:
        refreshed, error = _refresh_locked(request, path, oauth, refresh_token)
        row = _refresh_result(error, plan)
        if row:
            return row
        if refreshed:
            token = str(refreshed.get("accessToken") or token).strip()
        if refreshed or expired:
            response = _usage(request, token)

    if response.status != 200:
        return common.status_row(PROVIDER, response, plan)
    if not isinstance(response.data, dict):
        return common.error_row(PROVIDER, "malformed-response", plan)

    return common.finish(PROVIDER, parse(response.data), _live_plan(request, token, plan))
