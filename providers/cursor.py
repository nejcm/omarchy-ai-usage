"""Cursor subscription usage via Cursor's dashboard Connect endpoints."""

from __future__ import annotations

import json
import math
import os

from . import common

ID = "cursor"
NAME = "Cursor"
ABBREV = "U"
PROVIDER = (ID, NAME, ABBREV)
HOSTS = ("api2.cursor.sh",)
USAGE_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
PLAN_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetPlanInfo"


def credentials_path(home: str, env: dict) -> str:
    base = str(env.get("XDG_CONFIG_HOME") or "").strip() or os.path.join(home, ".config")
    return os.path.join(os.path.expanduser(base), "cursor", "auth.json")


def read_credentials(home: str, env: dict):
    try:
        with open(credentials_path(home, env), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, common.NOT_SIGNED_IN
    except (OSError, ValueError):
        return None, "malformed-auth"
    token = str(data.get("accessToken") or "").strip() if isinstance(data, dict) else ""
    if not token:
        return None, common.NOT_SIGNED_IN
    return {"access_token": token}, None


def _derived_total(plan_usage: dict):
    try:
        limit = float(plan_usage.get("limit"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(limit) or limit <= 0:
        return None
    spent = plan_usage.get("totalSpend")
    if spent is None:
        try:
            spent = limit - float(plan_usage.get("remaining"))
        except (TypeError, ValueError):
            return None
    try:
        spent = float(spent)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(spent):
        return None
    result = spent / limit * 100.0
    if not math.isfinite(result):
        return None
    return max(0.0, min(100.0, result))


def parse(payload: dict) -> list:
    plan_usage = payload.get("planUsage")
    if not isinstance(plan_usage, dict):
        plan_usage = {}
    reset = common.reset_iso(payload.get("billingCycleEnd"))
    metrics = []
    total = common.percent(plan_usage.get("totalPercentUsed"))
    if total is None:
        total = _derived_total(plan_usage)
    if total is not None:
        metrics.append(common.metric("Total usage", total, reset))
    for key, label in (("autoPercentUsed", "Cursor models"), ("apiPercentUsed", "Other models")):
        metric = common.metric(label, common.percent(plan_usage.get(key)), reset)
        if metric:
            metrics.append(metric)
    return metrics


def connect_headers(token: str) -> dict:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
    }


def collect(request, home: str, env: dict) -> dict:
    credentials, code = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(PROVIDER, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(PROVIDER, code)

    if common.is_expired_jwt(credentials["access_token"]):
        return common.row(PROVIDER, common.EXPIRED, error="auth-expired")

    headers = connect_headers(credentials["access_token"])
    response = request("POST", USAGE_URL, HOSTS, headers, body=b"{}")
    if response.status != 200:
        return common.status_row(PROVIDER, response)
    if not isinstance(response.data, dict):
        return common.error_row(PROVIDER, "malformed-response")

    plan = ""
    plan_response = request("POST", PLAN_URL, HOSTS, headers, body=b"{}")
    if plan_response.status == 200 and isinstance(plan_response.data, dict):
        info = plan_response.data.get("planInfo")
        if isinstance(info, dict):
            plan = str(info.get("planName") or "").strip()

    return common.finish(PROVIDER, parse(response.data), plan)
