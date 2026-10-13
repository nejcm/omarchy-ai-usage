"""OpenCode message usage from its local SQLite database; opened read-only."""

from __future__ import annotations

import contextlib
import math
import os
import pathlib
import sqlite3

import local_usage.scan
from providers import opencode

ID = "opencode"
MAX_INT = 2 ** 63 - 1
SELECT = """
SELECT id, session_id, time_created,
       json_extract(valid, '$.modelID'),
       json_extract(valid, '$.tokens.input'),
       json_extract(valid, '$.tokens.output'),
       json_extract(valid, '$.tokens.reasoning'),
       json_extract(valid, '$.tokens.cache.read'),
       json_extract(valid, '$.tokens.cache.write')
FROM (SELECT id, session_id, time_created, CASE WHEN json_valid(data) THEN data END AS valid
      FROM message WHERE time_created >= ?)
WHERE json_extract(valid, '$.role') = 'assistant'
  AND json_type(valid, '$.tokens.input') IN ('integer', 'real')
  AND json_type(valid, '$.tokens.output') IN ('integer', 'real')
  AND json_type(valid, '$.tokens.reasoning') IN ('integer', 'real')
  AND json_type(valid, '$.tokens.cache.read') IN ('integer', 'real')
  AND json_type(valid, '$.tokens.cache.write') IN ('integer', 'real')
"""


def query(home: str, env: dict) -> local_usage.scan.Query:
    """The message-table source; a missing database yields no events."""
    return local_usage.scan.Query(ID, lambda cutoff: _events(database_path(home, env), cutoff))


def database_path(home: str, env: dict) -> str:
    return os.path.join(opencode.data_directory(home, env), "opencode.db")


def _events(path, cutoff):
    if not os.path.exists(path):
        return []
    try:
        uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as connection:
            records = connection.execute(SELECT, (int(cutoff * 1000),)).fetchall()
    except sqlite3.Error:
        return []
    events = []
    for message_id, session, created, model, input_tokens, output, reasoning, cache_read, cache_write in records:
        counts = [_count(value) for value in (input_tokens, output, reasoning, cache_read, cache_write)]
        if not isinstance(message_id, str) or not message_id or not isinstance(session, str):
            continue
        if model is not None and not isinstance(model, str):
            continue
        if isinstance(created, bool) or not isinstance(created, (int, float)) or not math.isfinite(created) or None in counts:
            continue
        events.append({
            "key": "opencode:%s" % message_id,
            "ts": created / 1000,
            "session": session,
            "model": model or "",
            "input": counts[0],
            "output": counts[1],
            "reasoning": counts[2],
            "cache_read": counts[3],
            "cache_write": counts[4],
        })
    return events


def _count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    count = int(value)
    return count if 0 <= count <= MAX_INT else None
