"""Antigravity subscription usage via Google Cloud Code's quota summary."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import common

ID = "antigravity"
NAME = "Antigravity"
ABBREV = "A"
PROVIDER = (ID, NAME, ABBREV)
HOSTS = ("cloudcode-pa.googleapis.com",)
USAGE_URL = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"

BUCKETS = (
    ("gemini-5h", "Session", 5 * 60),
    ("gemini-weekly", "Weekly", 7 * 24 * 60),
    ("3p-5h", "Claude", 5 * 60),
    ("3p-weekly", "Claude Weekly", 7 * 24 * 60),
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
    # No client secret to refresh with, so an expired token means sign-in expired.
    expiry = common.parse_time(value)
    return expiry is not None and expiry <= datetime.now(timezone.utc)


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
            fraction = common.number(bucket.get("remainingFraction"))
            if bucket_id in buckets or fraction is None:
                continue
            buckets[bucket_id] = (max(0.0, min(1.0, fraction)), common.reset_iso(bucket.get("resetTime")))

    metrics = []
    for bucket_id, label, minutes in BUCKETS:
        entry = buckets.get(bucket_id)
        if entry is None:
            continue
        fraction, reset = entry
        metric = common.metric(label, common.percent((1.0 - fraction) * 100.0), reset, minutes)
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
        return common.row(PROVIDER, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(PROVIDER, code)

    if _is_expired(credentials["expiry"]):
        return common.row(PROVIDER, common.EXPIRED, error="auth-expired")

    headers = _headers(credentials["access_token"])
    response = request("POST", USAGE_URL, HOSTS, headers, body=b"{}")
    if response.status != 200:
        return common.status_row(PROVIDER, response)
    if not isinstance(response.data, dict):
        return common.error_row(PROVIDER, "malformed-response")

    return common.finish(PROVIDER, parse(response.data))
