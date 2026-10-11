"""Cursor subscription usage via Cursor's dashboard Connect endpoints.

Reads the CLI/agent token from ~/.config/cursor/auth.json. The token is used
read-only; refreshing it would rewrite that file, which this helper never does.
"""

from __future__ import annotations

import json
import os

from . import common

ID = "cursor"
NAME = "Cursor"
ABBREV = "U"
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


def parse(payload: dict) -> list:
    plan_usage = payload.get("planUsage") or {}
    reset = common.reset_iso(payload.get("billingCycleEnd"))
    metrics = []
    for key, label in (("totalPercentUsed", "Total usage"),
                       ("autoPercentUsed", "Cursor models"),
                       ("apiPercentUsed", "Other models")):
        value = common.percent(plan_usage.get(key))
        if value is not None:
            metrics.append(common.metric(label, value, reset))
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
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(ID, NAME, ABBREV, code)

    if common.is_expired_jwt(credentials["access_token"]):
        return common.row(ID, NAME, ABBREV, common.EXPIRED, error="auth-expired")

    headers = connect_headers(credentials["access_token"])
    response = request("POST", USAGE_URL, HOSTS, headers, body=b"{}")
    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response")

    plan = ""
    plan_response = request("POST", PLAN_URL, HOSTS, headers, body=b"{}")
    if plan_response.status == 200 and isinstance(plan_response.data, dict):
        info = plan_response.data.get("planInfo") or {}
        plan = str(info.get("planName") or "").strip()

    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, plan=plan, error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, plan=plan, metrics=metrics)
