"""Codex session rollouts as a local_usage.scan source; reads local JSONL only."""

from __future__ import annotations

import json
import math
import os

import local_usage.scan
from providers import common

ID = "codex"
MAX_INT = 2 ** 63 - 1
FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
          "output_tokens", "reasoning_output_tokens", "total_tokens")


def source(home: str, env: dict) -> local_usage.scan.Source:
    """The sessions and archived_sessions rollout sources under $CODEX_HOME or ~/.codex."""
    root = os.path.expanduser(env.get("CODEX_HOME") or os.path.join(home, ".codex"))
    return local_usage.scan.Source(ID, (os.path.join(root, "sessions", "**", "*.jsonl"),
                                        os.path.join(root, "archived_sessions", "**", "*.jsonl")), parse)


def parse(line: bytes, state: dict, offset: int) -> list:
    """Usage events from one rollout line; keys carry the line's byte offset."""
    if b"session_meta" not in line and b"token_count" not in line and b"turn_context" not in line:
        return []
    try:
        record = json.loads(line)
    except ValueError:
        return []
    if not isinstance(record, dict):
        return []
    kind = record.get("type")
    if kind == "session_meta":
        _session(record, state)
    elif kind == "turn_context":
        _turn(record, state)
    elif kind == "event_msg":
        return _tokens(record, state, offset)
    return []


def _session(record, state) -> None:
    if state.get("header"):
        return
    state["header"] = True
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return
    session = payload.get("id")
    if not isinstance(session, str) or not session:
        return
    state["session"] = session
    if payload.get("forked_from_id"):
        state["forked"] = True
        timestamp = common.parse_time(record.get("timestamp"))
        if timestamp is not None:
            state["fork_ts"] = timestamp.timestamp()


def _turn(record, state) -> None:
    payload = record.get("payload")
    model = payload.get("model") if isinstance(payload, dict) else None
    if isinstance(model, str) and model:
        state["model"] = model


def _tokens(record, state, offset) -> list:
    payload = record.get("payload")
    info = payload.get("info") if isinstance(payload, dict) and payload.get("type") == "token_count" else None
    last = _usage(info.get("last_token_usage") if isinstance(info, dict) else None)
    total = _usage(info.get("total_token_usage") if isinstance(info, dict) else None)
    timestamp = common.parse_time(record.get("timestamp"))
    session = state.get("session")
    if last is None or total is None or timestamp is None or not session:
        return []
    moment = timestamp.timestamp()
    if state.get("forked") and (state.get("fork_ts") is None or moment < state["fork_ts"]):
        return []
    signature = last + total
    if state.get("signature") == list(signature):
        return []
    state["signature"] = list(signature)
    input_tokens, cached, _, output_tokens, reasoning, _ = last
    cached = min(cached, input_tokens)
    reasoning = min(reasoning, output_tokens)
    return [{
        "key": "codex:%s:%d" % (session, offset),
        "ts": moment,
        "session": session,
        "model": state.get("model") or "",
        "input": input_tokens - cached,
        "cache_read": cached,
        "cache_write": 0,
        "output": output_tokens - reasoning,
        "reasoning": reasoning,
    }]


def _usage(value):
    if not isinstance(value, dict):
        return None
    counts = tuple(_count(value.get(name)) for name in FIELDS)
    return counts if None not in counts else None


def _count(value):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    count = int(value)
    return count if 0 <= count <= MAX_INT else None
