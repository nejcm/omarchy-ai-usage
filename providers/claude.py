"""Claude Code usage, refreshing its OAuth token under the CLI's own lock."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time

from . import common

ID = "claude"
NAME = "Claude Code"
ABBREV = "C"
HOSTS = ("api.anthropic.com", "platform.claude.com")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
LOCK_NAME = ".oauth_refresh.lock"
LOCK_STALE_SECONDS = 60
OAUTH_ERRORS = {"invalid_grant", "invalid_scope", "invalid_client",
                "invalid_request", "unauthorized_client", "unsupported_grant_type"}


def credentials_path(home: str, env: dict) -> str:
    base = env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    return os.path.join(os.path.expanduser(base), ".credentials.json")


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
    for key, label in (("five_hour", "Session"), ("seven_day", "Weekly")):
        bucket = payload.get(key)
        if not isinstance(bucket, dict):
            continue
        metric = common.metric(label, common.percent(bucket.get("utilization")),
                               common.reset_iso(bucket.get("resets_at")))
        if metric:
            metrics.append(metric)
    return metrics


# Proper-lockfile-compatible mutex: mkdir the lock dir, rmdir to release.
class _RefreshLock:

    def __init__(self, path: str):
        self.path = path
        self.held = False

    def acquire(self) -> bool:
        try:
            os.mkdir(self.path)
            self.held = True
            return True
        except FileExistsError:
            pass
        except OSError:
            return False
        try:
            age = time.time() - os.stat(self.path).st_mtime
        except OSError:
            return False
        if age <= LOCK_STALE_SECONDS:
            return False
        try:
            os.rmdir(self.path)
            os.mkdir(self.path)
            self.held = True
            return True
        except OSError:
            return False

    def release(self) -> None:
        if self.held:
            self.held = False
            try:
                os.rmdir(self.path)
            except OSError:
                pass


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
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def refresh_access_token(request, refresh_token: str):
    """Exchange a refresh token; (fields, None) on success, else (None, code)."""
    if not refresh_token:
        return None, "no-refresh-token"
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "scope": SCOPES,
    }).encode("utf-8")
    response = request("POST", TOKEN_URL, HOSTS, {"Content-Type": "application/json"},
                       body=body, error_body=True)
    if response.status in (400, 401):
        if _oauth_error(response.data) == "invalid_grant":
            return None, "invalid_grant"
        return None, "refresh-rejected"
    if response.status != 200 or not isinstance(response.data, dict):
        return None, "refresh-failed"
    token = str(response.data.get("access_token") or "").strip()
    if not token:
        return None, "refresh-failed"
    expires = response.data.get("expires_in")
    if expires is not None and _finite_seconds(expires) is None:
        return None, "refresh-failed"
    return response.data, None


def persist_rotation(path: str, original: dict, rotated: dict) -> str:
    """Atomically write rotated tokens; 'ok', 'changed', 'unreadable', 'write-failed'."""
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

    oauth = dict(current)
    oauth["accessToken"] = access
    if str(rotated.get("refresh_token") or "").strip():
        oauth["refreshToken"] = str(rotated["refresh_token"]).strip()
    seconds = _finite_seconds(rotated.get("expires_in"))
    if seconds is not None:
        oauth["expiresAt"] = round((time.time() + seconds) * 1000)
    updated = dict(document, claudeAiOauth=oauth)

    directory = os.path.dirname(path) or "."
    try:
        handle_fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".credentials.", suffix=".tmp")
    except OSError:
        return "write-failed"
    try:
        os.fchmod(handle_fd, 0o600)
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(updated, handle)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return "write-failed"
    return "ok"


def _refresh_locked(request, path: str, original: dict, refresh_token: str):
    """Reread, refresh, and persist while holding the CLI's refresh lock."""
    lock = _RefreshLock(os.path.join(os.path.dirname(path) or ".", LOCK_NAME))
    if not lock.acquire():
        return None, "refresh-locked", False
    try:
        current, _ = _read_oauth(path)
        if current is not None and current != original:
            return current, None, True
        fields, error = refresh_access_token(request, refresh_token)
        if error:
            return None, error, False
        status = persist_rotation(path, original, fields)
        if status == "changed":
            current, _ = _read_oauth(path)
            if current is not None:
                return current, None, True
            return None, "persist-changed", False
        if status != "ok":
            return None, "persist-" + status, False
        oauth = dict(original)
        oauth["accessToken"] = str(fields["access_token"]).strip()
        if str(fields.get("refresh_token") or "").strip():
            oauth["refreshToken"] = str(fields["refresh_token"]).strip()
        seconds = _finite_seconds(fields.get("expires_in"))
        if seconds is not None:
            oauth["expiresAt"] = round((time.time() + seconds) * 1000)
        return oauth, None, False
    finally:
        lock.release()


def _refresh_result(error, plan: str):
    if error == "invalid_grant":
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN, plan=plan, error="invalid-grant")
    if error == "no-refresh-token":
        return common.row(ID, NAME, ABBREV, common.EXPIRED, plan=plan, error="auth-expired")
    if error and (error == "refresh-locked" or error.startswith("persist-") or error == "refresh-rejected"):
        return common.error_row(ID, NAME, ABBREV, error, plan)
    return None


def _usage(request, token: str):
    return request("GET", USAGE_URL, HOSTS, {
        "Authorization": "Bearer " + token,
        "anthropic-beta": "oauth-2025-04-20",
    })


def collect(request, home: str, env: dict) -> dict:
    oauth, code, path = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(ID, NAME, ABBREV, code)

    plan = plan_label(oauth)
    refresh_token = str(oauth.get("refreshToken") or "").strip()
    token = str(oauth.get("accessToken")).strip()
    attempted = False

    if common.is_expired_ms(oauth.get("expiresAt")):
        attempted = True
        refreshed, error, _ = _refresh_locked(request, path, oauth, refresh_token)
        row = _refresh_result(error, plan)
        if row:
            return row
        if refreshed:
            token = str(refreshed.get("accessToken") or token).strip()

    response = _usage(request, token)
    if response.status == 401 and not attempted:
        attempted = True
        refreshed, error, _ = _refresh_locked(request, path, oauth, refresh_token)
        row = _refresh_result(error, plan)
        if row:
            return row
        if refreshed:
            token = str(refreshed.get("accessToken") or token).strip()
            response = _usage(request, token)

    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response, plan)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response", plan)

    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, plan=plan, error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, plan=plan, metrics=metrics)
