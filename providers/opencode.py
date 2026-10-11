"""OpenCode Go usage via OpenCode's usage endpoint (reads auth.json)."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime

from . import common

ID = "opencode"
NAME = "OpenCode"
ABBREV = "O"
HOSTS = ("opencode.ai",)
USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
SESSION_SECONDS = 18000
PLACEHOLDER_TOLERANCE = 2


def data_directory(home: str, env: dict) -> str:
    if str(env.get("OPENCODE_DATA_DIR") or "").strip():
        return os.path.expanduser(str(env["OPENCODE_DATA_DIR"]).strip())
    xdg = str(env.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        return os.path.join(os.path.expanduser(xdg), "opencode")
    return os.path.join(home, ".local", "share", "opencode")


def credentials_path(home: str, env: dict) -> str:
    return os.path.join(data_directory(home, env), "auth.json")


def read_credentials(home: str, env: dict):
    try:
        with open(credentials_path(home, env), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, common.NOT_SIGNED_IN
    except (OSError, ValueError):
        return None, "malformed-auth"
    entry = data.get("opencode-go") if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        entry = {}
    key = str(entry.get("key") or "").strip()
    if not key:
        return None, common.NOT_SIGNED_IN
    return {"key": key}, None


def _idle_placeholder(reset_iso: str) -> bool:
    if not reset_iso:
        return False
    try:
        target = datetime.fromisoformat(reset_iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return abs((target - time.time()) - SESSION_SECONDS) <= PLACEHOLDER_TOLERANCE


def parse(payload: dict) -> list:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    metrics = []
    for key, label in (("rolling", "Session"), ("weekly", "Weekly"), ("monthly", "Monthly")):
        window = usage.get(key)
        if not isinstance(window, dict):
            continue
        pct = common.percent(window.get("percent"))
        if pct is None:
            continue
        reset = common.reset_iso(window.get("resetsAt"))
        if key == "rolling" and pct == 0 and _idle_placeholder(reset):
            reset = ""
        metric = common.metric(label, pct, reset)
        if metric:
            metrics.append(metric)
    return metrics


def collect(request, home: str, env: dict) -> dict:
    credentials, code = read_credentials(home, env)
    if code == common.NOT_SIGNED_IN:
        return common.row(ID, NAME, ABBREV, common.NOT_SIGNED_IN)
    if code:
        return common.error_row(ID, NAME, ABBREV, code)

    # A browser-like User-Agent is required: Python's default is blocked by WAF.
    response = request("GET", USAGE_URL, HOSTS, {
        "Authorization": "Bearer " + credentials["key"],
        "User-Agent": "omarchy-ai-usage/1.0",
    })
    if response.status == 403:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, error="no-subscription")
    if response.status != 200:
        return common.status_row(ID, NAME, ABBREV, response)
    if not isinstance(response.data, dict):
        return common.error_row(ID, NAME, ABBREV, "malformed-response")

    metrics = parse(response.data)
    if not metrics:
        return common.row(ID, NAME, ABBREV, common.UNAVAILABLE, plan="Go", error="no-data")
    return common.row(ID, NAME, ABBREV, common.OK, plan="Go", metrics=metrics)
