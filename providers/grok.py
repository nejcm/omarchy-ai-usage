"""Grok Build subscription usage via the Grok CLI's billing proxy."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime

from . import common

ID = "grok"
NAME = "Grok"
ABBREV = "G"
HOSTS = ("cli-chat-proxy.grok.com",)
USAGE_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
PLAN_URL = "https://cli-chat-proxy.grok.com/v1/settings"
WEEKLY_PERIOD = "USAGE_PERIOD_TYPE_WEEKLY"
API_KEY_SCOPE = "xai::api_key"


def credentials_path(home: str, env: dict) -> str:
    base = str(env.get("GROK_HOME") or "").strip() or os.path.join(home, ".grok")
    return os.path.join(os.path.expanduser(base), "auth.json")


def read_credentials(home: str, env: dict):
    try:
        with open(credentials_path(home, env), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, common.NOT_SIGNED_IN
    except (OSError, ValueError):
        return None, "malformed-auth"
    # Billing needs a grok.com OAuth login; the API-key scope can never satisfy it.
    entries = []
    if isinstance(data, dict):
        for scope, entry in data.items():
            if scope == API_KEY_SCOPE or not isinstance(entry, dict):
                continue
            token = str(entry.get("key") or "").strip()
            if token:
                entries.append(token)
    if not entries:
        return None, common.NOT_SIGNED_IN
    for token in entries:
        if not common.is_expired_jwt(token):
            return {"access_token": token}, None
    return {"access_token": entries[0]}, None


def _epoch(value):
    iso = common.reset_iso(value)
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None


def _period(config: dict):
    period = config.get("currentPeriod")
    if not isinstance(period, dict):
        period = {}
    start = _epoch(period.get("start"))
    end = _epoch(period.get("end"))
    if start is None or end is None or end <= start:
        return "", ""
    return str(period.get("type") or "").strip(), common.reset_iso(period.get("end"))


def _cent(value, default=None):
    if value is None:
        return default
    if not isinstance(value, dict):
        return None
    val = value.get("val")
    if val is None:
        return 0.0
    if isinstance(val, bool):
        return None
    try:
        number = float(val)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse(payload: dict) -> list:
    config = payload.get("config")
    if not isinstance(config, dict):
        config = {}
    period_type, period_end = _period(config)
    metrics = []
    if period_type == WEEKLY_PERIOD:
        # proto-JSON drops a zero percent, so an absent field is a genuine 0.
        metric = common.metric("Weekly", common.percent(config.get("creditUsagePercent", 0)), period_end)
        if metric:
            metrics.append(metric)
    cap = _cent(config.get("onDemandCap"), 0.0)
    if cap and cap > 0:
        used = _cent(config.get("onDemandUsed"), 0.0)
        if used is not None:
            metric = common.metric("Pay as you go", common.percent(used / cap * 100.0), period_end)
            if metric:
                metrics.append(metric)
    return metrics


def _headers(token: str) -> dict:
    return {"Authorization": "Bearer " + token, "X-XAI-Token-Auth": "xai-grok-cli"}


def collect(request, home: str, env: dict) -> dict:
    credentials, code = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(ID, NAME, ABBREV, code)

    if common.is_expired_jwt(credentials["access_token"]):
        return common.row(ID, NAME, ABBREV, common.EXPIRED, error="auth-expired")

    headers = _headers(credentials["access_token"])
    response = request("GET", USAGE_URL, HOSTS, headers)
    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response")

    plan = ""
    plan_response = request("GET", PLAN_URL, HOSTS, headers)
    if plan_response.status == 200 and isinstance(plan_response.data, dict):
        plan = str(plan_response.data.get("subscription_tier_display") or "").strip()

    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, plan=plan, error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, plan=plan, metrics=metrics)
