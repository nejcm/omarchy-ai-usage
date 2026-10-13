"""Claude Code project transcripts as a local_usage.scan source; reads local JSONL only."""

from __future__ import annotations

import json
import math
import os

import local_usage.scan
from providers import common

ID = "claude"
# Equal totals still take a greater reasoning split.
MERGE = ("ON CONFLICT(key) DO UPDATE SET output = excluded.output, reasoning = excluded.reasoning"
         " WHERE excluded.output + excluded.reasoning > output + reasoning"
         " OR (excluded.output + excluded.reasoning = output + reasoning AND excluded.reasoning > reasoning)")
MAX_INT = 2 ** 63 - 1


def source(home: str, env: dict) -> local_usage.scan.Source:
    """The projects transcript source under $CLAUDE_CONFIG_DIR or ~/.claude."""
    root = common.claude_config_directory(home, env.get("CLAUDE_CONFIG_DIR"))
    return local_usage.scan.Source(ID, (os.path.join(root, "projects", "**", "*.jsonl"),), parse, MERGE)


def parse(line: bytes, state: dict, offset: int) -> list:
    """Usage events from one transcript line; keys are global so replays converge."""
    if b'"usage"' not in line:
        return []
    try:
        record = json.loads(line)
    except ValueError:
        return []
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return []
    message = record.get("message")
    if not isinstance(message, dict) or message.get("model") == "<synthetic>":
        return []
    message_id = message.get("id")
    usage = message.get("usage")
    if not isinstance(message_id, str) or not message_id or not isinstance(usage, dict):
        return []
    session, model, request = record.get("sessionId"), message.get("model"), record.get("requestId")
    if any(value is not None and not isinstance(value, str) for value in (session, model, request)):
        return []
    timestamp = common.parse_time(record.get("timestamp"))
    if timestamp is None:
        return []
    counts = {name: _count(usage.get(name)) for name in
              ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")}
    details = usage.get("output_tokens_details")
    thinking = _count(details.get("thinking_tokens")) if isinstance(details, dict) else 0
    if None in counts.values() or thinking is None:
        return []
    output = counts["output_tokens"]
    reasoning = min(thinking, output)
    return [{
        "key": "claude:%s:%s" % (message_id, request or ""),
        "ts": timestamp.timestamp(),
        "session": session or "",
        "model": model or "",
        "input": counts["input_tokens"],
        "cache_read": counts["cache_read_input_tokens"],
        "cache_write": counts["cache_creation_input_tokens"],
        "output": output - reasoning,
        "reasoning": reasoning,
    }]


def _count(value):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    count = int(value)
    return count if 0 <= count <= MAX_INT else None
