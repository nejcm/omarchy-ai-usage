"""Antigravity CLI per-call usage from its conversation SQLite databases; opened read-only."""

from __future__ import annotations

import contextlib
import glob
import os
import pathlib
import sqlite3

import local_usage.scan

ID = "antigravity"
MAX_INT = 2 ** 63 - 1


def query(home: str, env: dict) -> local_usage.scan.Query:
    """The Antigravity conversations source; a missing directory yields no events."""
    return local_usage.scan.Query(ID, lambda cutoff: _events(home, cutoff))


def conversations_directory(home: str) -> str:
    return os.path.join(home, ".gemini", "antigravity-cli", "conversations")


def acp_conversations_pattern(home: str) -> str:
    """T3 Code runs agy over ACP with a per-install data dir instead of ~/.gemini."""
    return os.path.join(home, ".t3", "userdata", "providers", "antigravity", "*", "antigravity-acp", "conversations")


def _events(home, cutoff):
    events = []
    paths = glob.glob(os.path.join(conversations_directory(home), "*.db"))
    paths += glob.glob(os.path.join(acp_conversations_pattern(home), "*.db"))
    for path in sorted(paths):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
            uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True)) as connection:
                events.extend(_conversation(connection, pathlib.Path(path).stem))
        except (OSError, sqlite3.Error):
            continue
    return events


def _conversation(connection, session):
    steps = dict(connection.execute("SELECT idx, metadata FROM steps"))
    started = _created(_first(connection.execute("SELECT data FROM trajectory_metadata_blob").fetchone()), 2)
    events = []
    for index, data in connection.execute("SELECT idx, data FROM gen_metadata"):
        try:
            event = _generation(data, steps, started)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, UnicodeDecodeError):
            continue
        if event:
            event.update(key="antigravity:%s:%d" % (session, index), session=session)
            events.append(event)
    return events


def _generation(data, steps, started):
    generation = _fields(_fields(data)[1][0])
    usage = _fields(generation[4][0])
    labels = dict(_entry(entry) for entry in generation.get(20, ()))
    step = labels.get("last_step_index")
    moment = _created(steps.get(int(step)), 1) if step and step.isdigit() else None
    moment = moment or started
    if moment is None:
        return None
    output, reasoning = _count(usage, 3), _count(usage, 9)
    return {
        "ts": moment,
        "model": _first(generation.get(19), b"").decode(),
        "input": _count(usage, 2),
        "cache_read": _count(usage, 5),
        "cache_write": _count(usage, 4),
        "output": max(output - reasoning, 0),
        "reasoning": min(reasoning, output),
    }


def _count(usage, field):
    value = _first(usage.get(field), 0)
    if not isinstance(value, int) or value > MAX_INT:
        raise ValueError("count")
    return value


def _entry(data):
    fields = _fields(data)
    return fields[1][0].decode(), fields[2][0].decode()


def _created(metadata, field):
    """Seconds of the google.protobuf.Timestamp in `field`, or None."""
    if not isinstance(metadata, bytes):
        return None
    try:
        seconds = _first(_fields(_fields(metadata)[field][0]).get(1))
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return float(seconds) if isinstance(seconds, int) and seconds > 0 else None


def _first(values, default=None):
    return values[0] if values else default


def _fields(data):
    """Top-level protobuf fields as {number: [int | bytes]}; fixed-width values are skipped."""
    fields, index = {}, 0
    while index < len(data):
        key, index = _varint(data, index)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, index = _varint(data, index)
        elif wire == 2:
            length, index = _varint(data, index)
            value, index = bytes(data[index:index + length]), index + length
            if index > len(data):
                raise ValueError("truncated")
        elif wire in (1, 5):
            index += 8 if wire == 1 else 4
            continue
        else:
            raise ValueError("wire type %d" % wire)
        fields.setdefault(number, []).append(value)
    return fields


def _varint(data, index):
    result = shift = 0
    while True:
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, index
        shift += 7
        if shift > 63:
            raise ValueError("varint")
