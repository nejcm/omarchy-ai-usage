"""Codex subscription usage via the ChatGPT backend usage endpoint."""

from __future__ import annotations

import json
import os
import time

from . import common

ID = "codex"
NAME = "Codex"
ABBREV = "X"
HOSTS = ("chatgpt.com",)
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def credentials_path(home: str, env: dict) -> str:
    base = env.get("CODEX_HOME") or os.path.join(home, ".codex")
    return os.path.join(os.path.expanduser(base), "auth.json")


def read_credentials(home: str, env: dict):
    try:
        with open(credentials_path(home, env), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, common.NOT_SIGNED_IN
    except (OSError, ValueError):
        return None, "malformed-auth"
    tokens = data.get("tokens") if isinstance(data, dict) else None
    token = str((tokens or {}).get("access_token") or "").strip()
    if not token:
        if str(data.get("OPENAI_API_KEY") or "").strip():
            return None, "api-key-auth"
        return None, common.NOT_SIGNED_IN
    return {"access_token": token, "account_id": str((tokens or {}).get("account_id") or "").strip()}, None


def format_plan(value) -> str:
    raw = str(value or "").strip()
    table = {"prolite": "Pro 100", "pro": "Pro 200", "promax": "Pro 500"}
    if not raw:
        return ""
    return table.get(raw.lower(), raw.replace("_", " ").title())


def parse(payload: dict) -> list:
    rate_limit = payload.get("rate_limit") or {}
    metrics = []
    for key, label in (("primary_window", "Session"), ("secondary_window", "Weekly")):
        window = rate_limit.get(key)
        if not isinstance(window, dict) or window.get("used_percent") is None:
            continue
        reset = common.reset_iso(window.get("reset_at"))
        if not reset and window.get("reset_after_seconds") is not None:
            try:
                reset = common.reset_iso(time.time() + float(window["reset_after_seconds"]))
            except (TypeError, ValueError):
                reset = ""
        metrics.append(common.metric(label, common.percent(window.get("used_percent")), reset))
    return metrics


def collect(request, home: str, env: dict) -> dict:
    credentials, code = read_credentials(home, env)
    if code == "api-key-auth":
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, error="api-key-auth")
    if code == common.NOT_SIGNED_IN:
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(ID, NAME, ABBREV, code)

    if common.is_expired_jwt(credentials["access_token"]):
        return common.row(ID, NAME, ABBREV, common.EXPIRED, error="auth-expired")

    headers = {"Authorization": "Bearer " + credentials["access_token"]}
    if credentials["account_id"]:
        headers["ChatGPT-Account-Id"] = credentials["account_id"]
    response = request("GET", USAGE_URL, HOSTS, headers)
    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response")

    plan = format_plan(response.data.get("plan_type"))
    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, plan=plan, error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, plan=plan, metrics=metrics)
