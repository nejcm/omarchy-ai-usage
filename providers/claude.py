"""Claude Code subscription usage via Anthropic's OAuth usage endpoint."""

from __future__ import annotations

import json
import os
import re

from . import common

ID = "claude"
NAME = "Claude Code"
ABBREV = "C"
HOSTS = ("api.anthropic.com",)
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def credentials_path(home: str, env: dict) -> str:
    base = env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    return os.path.join(os.path.expanduser(base), ".credentials.json")


def read_credentials(home: str, env: dict):
    try:
        with open(credentials_path(home, env), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, common.NOT_SIGNED_IN
    except (OSError, ValueError):
        return None, "malformed-auth"
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict) or not str(oauth.get("accessToken") or "").strip():
        return None, common.NOT_SIGNED_IN
    return oauth, None


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
        if isinstance(bucket, dict) and bucket.get("utilization") is not None:
            metrics.append(common.metric(label, common.percent(bucket.get("utilization")),
                                         common.reset_iso(bucket.get("resets_at"))))
    return metrics


def collect(request, home: str, env: dict) -> dict:
    oauth, code = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(ID, NAME, ABBREV, code)

    plan = plan_label(oauth)
    # Refreshing here would write to Claude Code's credential file; the CLI owns it.
    if common.is_expired_ms(oauth.get("expiresAt")):
        return common.row(ID, NAME, ABBREV, common.EXPIRED, plan=plan, error="auth-expired")

    response = request("GET", USAGE_URL, HOSTS, {
        "Authorization": "Bearer " + str(oauth["accessToken"]).strip(),
        "anthropic-beta": "oauth-2025-04-20",
    })
    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response, plan)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response", plan)

    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, plan=plan, error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, plan=plan, metrics=metrics)
