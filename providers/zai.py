"""Z.ai (GLM Coding Plan) subscription usage via Z.ai's quota endpoint."""

from __future__ import annotations

import json
import math
import os
import re
from urllib.parse import urlsplit

from . import common

ID = "zai"
NAME = "Z.ai"
ABBREV = "Z"
HOSTS = ("api.z.ai",)
QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
PLAN_URL = "https://api.z.ai/api/biz/subscription/list"

TOKEN_FIELDS = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
NULL_KEYS = ("", "null", "~", "undefined")
# Window units Z.ai reports: 3 hours, 4 days, 6 weeks, 5 months.
UNIT_MINUTES = {3: 60, 4: 1440, 6: 10080, 5: 43200}
SESSION_MAX_MINUTES = 1440
ORDER = ("Session", "Weekly", "Web searches")


def config_path(home: str) -> str:
    # Z.ai's own `chelper` CLI keeps its key here (homedir-based, not XDG).
    return os.path.join(home, ".chelper", "config.yaml")


def claude_settings_path(home: str, env: dict) -> str:
    base = str(env.get("CLAUDE_CONFIG_DIR") or "").strip() or os.path.join(home, ".claude")
    return os.path.join(os.path.expanduser(base), "settings.json")


def _yaml_scalar(value: str) -> str:
    value = value.strip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end > 0 else value.strip("'\"")
    return re.split(r"(?:^|\s)#", value, 1)[0].strip()


def _cli_key(home: str) -> str:
    try:
        with open(config_path(home), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""
    for line in text.splitlines():
        name, _, value = line.partition(":")
        if name.strip() != "api_key":
            continue
        value = _yaml_scalar(value)
        return "" if value in NULL_KEYS else value
    return ""


def _claude_key(document) -> str:
    # Only a Claude Code login pointed at Z.ai, so a plain Anthropic login is never read.
    env = document.get("env") if isinstance(document, dict) else None
    if not isinstance(env, dict):
        return ""
    if urlsplit(str(env.get("ANTHROPIC_BASE_URL") or "")).hostname != "api.z.ai":
        return ""
    for field in TOKEN_FIELDS:
        key = str(env.get(field) or "").strip()
        if key:
            return key
    return ""


def read_credentials(home: str, env: dict):
    # The CLI store is best-effort: an absent or keyless file never blocks the Claude log-in.
    key = _cli_key(home)
    if key:
        return {"api_key": key}, None
    try:
        with open(claude_settings_path(home, env), encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError:
        return None, common.NOT_SIGNED_IN
    except (OSError, ValueError):
        return None, "malformed-auth"
    key = _claude_key(document)
    if key:
        return {"api_key": key}, None
    return None, common.NOT_SIGNED_IN


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _window_minutes(unit, number):
    if unit is None or number is None or number <= 0:
        return None
    minutes = number * UNIT_MINUTES.get(int(unit), 0)
    return minutes or None


def parse(payload: dict) -> list:
    container = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(container, dict):
        container = payload if isinstance(payload, dict) else {}
    limits = container.get("limits")
    if not isinstance(limits, list):
        return []

    buckets = {}
    for entry in limits:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type") or entry.get("name")
        if kind in ("CREDIT_LIMIT", "TOKENS_LIMIT"):
            window = _window_minutes(_number(entry.get("unit")), _number(entry.get("number")))
            percent = common.percent(entry.get("percentage"))
            if window is None or percent is None:
                continue
            label = "Session" if window < SESSION_MAX_MINUTES else "Weekly"
            buckets.setdefault(label, common.metric(label, percent, common.reset_iso(entry.get("nextResetTime"))))
        elif kind == "TIME_LIMIT":
            used, limit = _number(entry.get("currentValue")), _number(entry.get("usage"))
            if used is None or limit is None or used < 0 or limit <= 0:
                continue
            metric = common.metric("Web searches", common.percent(used / limit * 100.0),
                                   common.reset_iso(entry.get("nextResetTime")))
            buckets.setdefault("Web searches", metric)
    return [buckets[label] for label in ORDER if label in buckets]


def _no_coding_plan(payload: dict) -> bool:
    return payload.get("success") is False and "coding plan" in str(payload.get("msg") or "").lower()


def _plan_name(payload: dict) -> str:
    entries = payload.get("data")
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        return ""
    return str(entries[0].get("productName") or "").strip()


def _headers(key: str) -> dict:
    return {"Authorization": "Bearer " + key}


def collect(request, home: str, env: dict) -> dict:
    credentials, code = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(ID, NAME, ABBREV, code)

    headers = _headers(credentials["api_key"])
    response = request("GET", QUOTA_URL, HOSTS, headers)
    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response")
    if _no_coding_plan(response.data):
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, error="no-coding-plan")

    plan = ""
    plan_response = request("GET", PLAN_URL, HOSTS, headers)
    if plan_response.status == 200 and isinstance(plan_response.data, dict):
        plan = _plan_name(plan_response.data)

    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, plan=plan, error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, plan=plan, metrics=metrics)
