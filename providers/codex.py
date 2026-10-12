"""Codex subscription usage via the ChatGPT backend usage endpoint."""

from __future__ import annotations

import json
import os
import time

from . import common

ID = "codex"
NAME = "Codex"
ABBREV = "X"
PROVIDER = (ID, NAME, ABBREV)
HOSTS = ("chatgpt.com",)
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
SESSION_SECONDS = 18000
WEEKLY_SECONDS = 604800


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
    document = data if isinstance(data, dict) else {}
    tokens = document.get("tokens")
    if not isinstance(tokens, dict):
        tokens = {}
    token = str(tokens.get("access_token") or "").strip()
    if not token:
        if str(document.get("OPENAI_API_KEY") or "").strip():
            return None, "api-key-auth"
        return None, common.NOT_SIGNED_IN
    return {"access_token": token, "account_id": str(tokens.get("account_id") or "").strip()}, None


def format_plan(value) -> str:
    raw = str(value or "").strip()
    table = {"prolite": "Pro 100", "pro": "Pro 200", "promax": "Pro 500"}
    if not raw:
        return ""
    return table.get(raw.lower(), raw.replace("_", " ").title())


def _kind(window: dict):
    try:
        seconds = float(window.get("limit_window_seconds"))
    except (TypeError, ValueError):
        return None
    if seconds == SESSION_SECONDS:
        return "session"
    if seconds == WEEKLY_SECONDS:
        return "weekly"
    return None


def _pick(candidates: list, kind: str):
    for window, fallback, exact in candidates:
        if exact == kind:
            return window
    for window, fallback, exact in candidates:
        if exact is None and fallback == kind:
            return window
    return None


def parse(payload: dict) -> list:
    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        rate_limit = {}
    candidates = []
    for key, fallback in (("primary_window", "session"), ("secondary_window", "weekly")):
        window = rate_limit.get(key)
        if isinstance(window, dict) and window.get("used_percent") is not None:
            candidates.append((window, fallback, _kind(window)))

    metrics = []
    for kind, label in (("session", "Session"), ("weekly", "Weekly")):
        window = _pick(candidates, kind)
        if window is None:
            continue
        pct = common.percent(window.get("used_percent"))
        if pct is None:
            continue
        reset = common.reset_iso(window.get("reset_at"))
        if not reset and window.get("reset_after_seconds") is not None:
            try:
                reset = common.reset_iso(time.time() + float(window["reset_after_seconds"]))
            except (TypeError, ValueError):
                reset = ""
        seconds = common.number(window.get("limit_window_seconds"))
        metric = common.metric(label, pct, reset, seconds / 60 if seconds and seconds > 0 else None)
        if metric:
            metrics.append(metric)
    return metrics


def collect(request, home: str, env: dict) -> dict:
    credentials, code = read_credentials(home, env)
    if code == "api-key-auth":
        return common.row(PROVIDER, common.UNAVAILABLE, error="api-key-auth")
    if code == common.NOT_SIGNED_IN:
        return common.row(PROVIDER, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(PROVIDER, code)

    if common.is_expired_jwt(credentials["access_token"]):
        return common.row(PROVIDER, common.EXPIRED, error="auth-expired")

    headers = {"Authorization": "Bearer " + credentials["access_token"]}
    if credentials["account_id"]:
        headers["ChatGPT-Account-Id"] = credentials["account_id"]
    response = request("GET", USAGE_URL, HOSTS, headers)
    if response.status != 200:
        return common.status_row(PROVIDER, response)
    if not isinstance(response.data, dict):
        return common.error_row(PROVIDER, "malformed-response")

    plan = format_plan(response.data.get("plan_type"))
    return common.finish(PROVIDER, parse(response.data), plan)
