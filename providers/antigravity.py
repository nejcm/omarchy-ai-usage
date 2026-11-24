"""Antigravity subscription usage via Google Cloud Code's quota summary."""

from __future__ import annotations

import json
import os
import urllib.parse
import subprocess
from datetime import datetime, timedelta, timezone

from . import common

ID = "antigravity"
NAME = "Antigravity"
ABBREV = "A"
PROVIDER = (ID, NAME, ABBREV)
# `agy`'s endpoint; the production host reports no Gemini usage for personal accounts.
HOSTS = ("daily-cloudcode-pa.googleapis.com",)
TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKEN_HOSTS = ("oauth2.googleapis.com",)
# `agy`'s installed-app OAuth client, public in its binary; Google does not treat it as secret.
CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
CLIENT_SECRET = "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"
USAGE_URL = "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
# shortcut: Google returns the Gemini groups only to an Antigravity client UA; bump if they disappear again.
USER_AGENT = "antigravity/hub/2.24.0 (aidev_client; os_type=linux; arch=x64; cl=963137146)"
KEYRING_LOOKUP = ("secret-tool", "lookup", "service", "gemini", "username", "antigravity")
WINDOWS = {"5h": ("", 5 * 60), "weekly": (" Weekly", 7 * 24 * 60)}
FAMILY_ORDER = ("Gemini", "Claude/GPT")
# Some backend replicas answer with an untracked quota: everything unused, each reset at now + window.
ATTEMPTS = 3
FRESH_TOLERANCE = timedelta(minutes=1)


def credentials_path(home: str, env: dict) -> str:
    # Plaintext `agy` token written only when no OS keyring is available (headless Linux).
    return os.path.join(home, ".gemini", "antigravity-cli", "antigravity-oauth-token")


def _read_keyring(env: dict):
    try:
        result = subprocess.run(KEYRING_LOOKUP, stdin=subprocess.DEVNULL, capture_output=True,
                                encoding="utf-8", errors="replace", env=env, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 and result.stdout.strip() else None


def read_credentials(home: str, env: dict):
    try:
        with open(credentials_path(home, env), encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        text = _read_keyring(env)
        if text is None:
            return None, common.NOT_SIGNED_IN
    except (OSError, ValueError):
        return None, "malformed-auth"
    try:
        data = json.loads(text)
    except ValueError:
        return None, "malformed-auth"
    document = data if isinstance(data, dict) else {}
    token = document.get("token")
    source = token if isinstance(token, dict) else document
    access = str(source.get("access_token") or "").strip()
    if not access:
        return None, common.NOT_SIGNED_IN
    refresh = str(source.get("refresh_token") or "").strip()
    return {"access_token": access, "refresh_token": refresh, "expiry": source.get("expiry")}, None


def _is_expired(value) -> bool:
    expiry = common.parse_time(value)
    return expiry is not None and expiry <= datetime.now(timezone.utc)


def _refresh(request, refresh_token: str):
    """In-memory refresh; `agy` keeps owning the stored token. (token, None) or (None, row)."""
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode("utf-8")
    response = request("POST", TOKEN_URL, TOKEN_HOSTS,
                       {"Content-Type": "application/x-www-form-urlencoded"}, body=body)
    if response.status in (400, 401):
        return None, common.row(PROVIDER, common.EXPIRED, error="auth-expired")
    if response.status != 200:
        return None, common.status_row(PROVIDER, response)
    data = response.data if isinstance(response.data, dict) else {}
    token = str(data.get("access_token") or "").strip()
    if not token:
        return None, common.error_row(PROVIDER, "refresh-failed")
    return token, None


def _family(bucket_id: str, group: dict) -> str:
    if bucket_id in ("gemini-5h", "gemini-weekly"):
        return "Gemini"
    if bucket_id.startswith("3p-"):
        return "Claude/GPT"
    return str(group.get("displayName") or bucket_id).strip()


def _rank(metric: dict) -> tuple:
    family = metric["family"]
    return (FAMILY_ORDER.index(family) if family in FAMILY_ORDER else len(FAMILY_ORDER), metric["windowMinutes"])


def parse(payload: dict) -> list:
    """Every 5-hour and weekly pool, except unused 5-hour pools other than Gemini's."""
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return []
    seen = set()
    metrics = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("buckets"), list):
            continue
        for bucket in group["buckets"]:
            if not isinstance(bucket, dict) or bucket.get("disabled") is True:
                continue
            bucket_id = str(bucket.get("bucketId") or "").strip()
            window = WINDOWS.get(str(bucket.get("window") or bucket_id.rsplit("-", 1)[-1]))
            fraction = common.number(bucket.get("remainingFraction"))
            if not bucket_id or bucket_id in seen or window is None or fraction is None:
                continue
            seen.add(bucket_id)
            family = _family(bucket_id, group)
            suffix, minutes = window
            used = common.percent((1.0 - max(0.0, min(1.0, fraction))) * 100.0)
            if used == 0 and not suffix and family != "Gemini":
                continue
            metric = common.metric(family + suffix, used, common.reset_iso(bucket.get("resetTime")), minutes)
            if metric:
                metrics.append(dict(metric, family=family))
    return [{k: v for k, v in metric.items() if k != "family"} for metric in sorted(metrics, key=_rank)]


def _is_untracked(payload: dict, now: datetime) -> bool:
    buckets = [bucket for group in payload.get("groups") or [] if isinstance(group, dict)
               for bucket in group.get("buckets") or [] if isinstance(bucket, dict)]
    for bucket in buckets:
        window = WINDOWS.get(str(bucket.get("window") or str(bucket.get("bucketId") or "").rsplit("-", 1)[-1]))
        reset = common.parse_time(bucket.get("resetTime"))
        if common.number(bucket.get("remainingFraction")) != 1 or window is None or reset is None:
            return False
        if abs(reset - now - timedelta(minutes=window[1])) > FRESH_TOLERANCE:
            return False
    return bool(buckets)


def _headers(token: str) -> dict:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


def collect(request, home: str, env: dict) -> dict:
    credentials, code = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(PROVIDER, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(PROVIDER, code)

    token = credentials["access_token"]
    if _is_expired(credentials["expiry"]):
        if not credentials["refresh_token"]:
            return common.row(PROVIDER, common.EXPIRED, error="auth-expired")
        token, failed = _refresh(request, credentials["refresh_token"])
        if failed:
            return failed

    headers = _headers(token)
    for _ in range(ATTEMPTS):
        response = request("POST", USAGE_URL, HOSTS, headers, body=b"{}")
        if response.status != 200:
            return common.status_row(PROVIDER, response)
        if not isinstance(response.data, dict):
            return common.error_row(PROVIDER, "malformed-response")
        if not _is_untracked(response.data, datetime.now(timezone.utc)):
            break

    return common.finish(PROVIDER, parse(response.data))
