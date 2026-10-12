"""Antigravity subscription usage via Google Cloud Code's quota summary."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

from . import common

ID = "antigravity"
NAME = "Antigravity"
ABBREV = "A"
HOSTS = ("cloudcode-pa.googleapis.com",)
USAGE_URL = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"

# bucketId -> label. Fixed order: Gemini pool first, then the Claude/GPT pool.
BUCKETS = (
    ("gemini-5h", "Session"),
    ("gemini-weekly", "Weekly"),
    ("3p-5h", "Claude"),
    ("3p-weekly", "Claude Weekly"),
)


def credentials_path(home: str, env: dict) -> str:
    # Plaintext `agy` token written only when no OS keyring is available (headless Linux).
    return os.path.join(home, ".gemini", "antigravity-cli", "antigravity-oauth-token")


def read_credentials(home: str, env: dict):
    try:
        with open(credentials_path(home, env), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, common.NOT_SIGNED_IN
    except (OSError, ValueError):
        return None, "malformed-auth"
    document = data if isinstance(data, dict) else {}
    token = document.get("token")
    source = token if isinstance(token, dict) else document
    access = str(source.get("access_token") or "").strip()
    if not access:
        return None, common.NOT_SIGNED_IN
    return {"access_token": access, "expiry": source.get("expiry")}, None


def _is_expired(value) -> bool:
    iso = common.reset_iso(value)
    if not iso:
        return False
    # Refresh needs a Google OAuth client secret the token file does not carry, so an
    # expired access token is sign-in expired rather than refreshable.
    return datetime.fromisoformat(iso.replace("Z", "+00:00")) <= datetime.now(timezone.utc)


def _fraction(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, number))


def parse(payload: dict) -> list:
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return []
    buckets = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_buckets = group.get("buckets")
        if not isinstance(group_buckets, list):
            continue
        for bucket in group_buckets:
            if not isinstance(bucket, dict):
                continue
            bucket_id = str(bucket.get("bucketId") or "").strip()
            fraction = _fraction(bucket.get("remainingFraction"))
            if bucket_id in buckets or fraction is None:
                continue
            buckets[bucket_id] = (fraction, common.reset_iso(bucket.get("resetTime")))

    metrics = []
    for bucket_id, label in BUCKETS:
        entry = buckets.get(bucket_id)
        if entry is None:
            continue
        fraction, reset = entry
        metric = common.metric(label, common.percent(round((1.0 - fraction) * 100.0)), reset)
        if metric:
            metrics.append(metric)
    return metrics


def _headers(token: str) -> dict:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "antigravity",
    }


def collect(request, home: str, env: dict) -> dict:
    credentials, code = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(ID, NAME, ABBREV, code)

    if _is_expired(credentials["expiry"]):
        return common.row(ID, NAME, ABBREV, common.EXPIRED, error="auth-expired")

    headers = _headers(credentials["access_token"])
    response = request("POST", USAGE_URL, HOSTS, headers, body=b"{}")
    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response")

    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, metrics=metrics)
