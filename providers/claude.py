"""Claude Code usage, refreshing its OAuth token in place when expired."""

from __future__ import annotations

import json
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


def credentials_path(home: str, env: dict) -> str:
    base = env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    return os.path.join(os.path.expanduser(base), ".credentials.json")


def read_credentials(home: str, env: dict):
    """Return (oauth, error code, path); oauth is the claudeAiOauth mapping."""
    path = credentials_path(home, env)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, common.NOT_SIGNED_IN, path
    except (OSError, ValueError):
        return None, "malformed-auth", path
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict) or not str(oauth.get("accessToken") or "").strip():
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
    response = request("POST", TOKEN_URL, HOSTS, {"Content-Type": "application/json"}, body=body)
    if response.status in (400, 401):
        # A rejected refresh means the stored login no longer works; re-login is the fix.
        return None, "invalid_grant"
    if response.status != 200 or not isinstance(response.data, dict):
        return None, "refresh-failed"
    token = str(response.data.get("access_token") or "").strip()
    if not token:
        return None, "refresh-failed"
    return response.data, None


def persist_rotation(path: str, original: dict, rotated: dict) -> bool:
    """Atomically write rotated tokens back, skipping if another process rotated."""
    access = str(rotated.get("access_token") or "").strip()
    if not access:
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return False
    if not isinstance(document, dict):
        return False
    current = document.get("claudeAiOauth")
    if not isinstance(current, dict):
        return False
    if str(current.get("accessToken") or "") != str(original.get("accessToken") or ""):
        return False

    oauth = dict(current)
    oauth["accessToken"] = access
    if str(rotated.get("refresh_token") or "").strip():
        oauth["refreshToken"] = str(rotated["refresh_token"]).strip()
    if rotated.get("expires_in") is not None:
        try:
            oauth["expiresAt"] = round((time.time() + float(rotated["expires_in"])) * 1000)
        except (TypeError, ValueError):
            pass
    updated = dict(document, claudeAiOauth=oauth)

    directory = os.path.dirname(path) or "."
    try:
        handle_fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".credentials.", suffix=".tmp")
    except OSError:
        return False
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
        return False
    return True


def _usage(request, token: str) -> dict:
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
    rotated = None
    attempted = False
    token = str(oauth.get("accessToken")).strip()

    if common.is_expired_ms(oauth.get("expiresAt")):
        attempted = True
        rotated, error = refresh_access_token(request, refresh_token)
        if error == "invalid_grant":
            return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN, error="invalid-grant")
        if rotated:
            token = str(rotated["access_token"]).strip()

    response = _usage(request, token)
    if response.status == 401 and not attempted:
        attempted = True
        rotated, error = refresh_access_token(request, refresh_token)
        if error == "invalid_grant":
            return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN, error="invalid-grant")
        if rotated:
            token = str(rotated["access_token"]).strip()
            response = _usage(request, token)

    if rotated:
        persist_rotation(path, oauth, rotated)

    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response, plan)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response", plan)

    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, plan=plan, error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, plan=plan, metrics=metrics)
