"""OpenCode Go subscription usage via OpenCode's usage endpoint.

Reads the `opencode-go` key from OpenCode's auth.json. OpenCode 2 can move the
credential into its channel SQLite databases after import; that migration is a
documented limitation, not read here.
"""

from __future__ import annotations

import json
import os

from . import common

ID = "opencode"
NAME = "OpenCode"
ABBREV = "O"
HOSTS = ("opencode.ai",)
USAGE_URL = "https://opencode.ai/zen/go/v1/usage"


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
    key = str((entry or {}).get("key") or "").strip()
    if not key:
        return None, common.NOT_SIGNED_IN
    return {"key": key}, None


def parse(payload: dict) -> list:
    usage = payload.get("usage") or {}
    metrics = []
    for key, label in (("rolling", "Session"), ("weekly", "Weekly"), ("monthly", "Monthly")):
        window = usage.get(key)
        if isinstance(window, dict) and window.get("percent") is not None:
            metrics.append(common.metric(label, common.percent(window.get("percent")),
                                         common.reset_iso(window.get("resetsAt"))))
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
