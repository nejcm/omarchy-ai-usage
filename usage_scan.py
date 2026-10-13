"""Incremental scan of local agent log files into a SQLite usage cache."""

from __future__ import annotations

import glob
import json
import os
import sqlite3
import stat
import time
from collections import namedtuple

STATE_DAYS = 31
MAX_LINE_BYTES = 16 * 1024 * 1024
BUDGET_BYTES = 256 * 1024 * 1024
BUSY_TIMEOUT_MS = 5000

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    path TEXT PRIMARY KEY, inode INTEGER NOT NULL, size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL, offset INTEGER NOT NULL, state TEXT NOT NULL,
    attempted REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
    key TEXT PRIMARY KEY, ts REAL NOT NULL, provider TEXT NOT NULL,
    session TEXT NOT NULL, model TEXT NOT NULL,
    input INTEGER NOT NULL, cache_read INTEGER NOT NULL, cache_write INTEGER NOT NULL,
    output INTEGER NOT NULL, reasoning INTEGER NOT NULL
);
"""

Source = namedtuple("Source", "id patterns parse merge", defaults=(None,))


def cache_directory(home: str, env: dict) -> str:
    xdg = str(env.get("XDG_CACHE_HOME") or "").strip()
    return os.path.join(os.path.expanduser(xdg) if xdg else os.path.join(home, ".cache"), "omarchy-ai-usage")


def database_path(home: str, env: dict) -> str:
    return os.path.join(cache_directory(home, env), "usage.db")


def open_database(path: str) -> sqlite3.Connection:
    """Open the usage cache, creating its directory and schema."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA busy_timeout = %d" % BUSY_TIMEOUT_MS)
    connection.executescript(SCHEMA)
    return connection


def discover(source, cutoff: float) -> list:
    """Regular files matching the source patterns with an mtime inside the window."""
    found = {}
    for pattern in source.patterns:
        for path in glob.glob(pattern, recursive=True):
            if path in found:
                continue
            try:
                metadata = os.stat(path)
            except OSError:
                continue
            if stat.S_ISREG(metadata.st_mode) and metadata.st_mtime >= cutoff:
                found[path] = metadata
    return sorted(found.items())


def scan(connection: sqlite3.Connection, sources, now=None, budget: int = BUDGET_BYTES) -> int:
    """Scan each source once and return the bytes of new log data read."""
    moment = time.time() if now is None else now
    cutoff = moment - STATE_DAYS * 86400
    attempted = dict(connection.execute("SELECT path, attempted FROM files"))
    candidates = [(path, metadata, source)
                  for source in sources for path, metadata in discover(source, cutoff)]
    read_bytes = 0
    for path, metadata, source in sorted(candidates,
                                         key=lambda entry: (attempted.get(entry[0], 0), entry[0])):
        if read_bytes >= budget:
            break
        read_bytes += _scan_file(connection, path, metadata, source, budget - read_bytes, moment)
    connection.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
    connection.commit()
    _forget_missing(connection)
    return read_bytes


def _scan_file(connection, path, metadata, source, budget, moment) -> int:
    offset, skip, state = _resume(connection, path, metadata)
    remaining = [budget]
    progress = {"offset": offset, "skip": skip}
    try:
        with open(path, "rb") as handle:
            handle.seek(offset + skip)
            for line in _lines(handle, MAX_LINE_BYTES, remaining, progress):
                if line is None:
                    continue
                start = progress["offset"] - len(line)  # _lines left progress at the end of this line
                for event in source.parse(line, state, start) or ():
                    _write_event(connection, source.id, event, source.merge)
    except Exception:
        connection.rollback()
        if budget - remaining[0]:
            _mark_attempted(connection, path, metadata, moment)  # a doomed file must not starve the rest
        return budget - remaining[0]
    if progress["skip"]:
        state["_skip"] = progress["skip"]  # bytes discarded from an oversized line, resumed by _resume
    connection.execute(
        "INSERT OR REPLACE INTO files(path, inode, size, mtime_ns, offset, state, attempted) VALUES(?,?,?,?,?,?,?)",
        (path, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, progress["offset"], json.dumps(state), moment))
    connection.commit()
    return budget - remaining[0]


def _mark_attempted(connection, path, metadata, moment) -> None:
    if connection.execute("UPDATE files SET attempted = ? WHERE path = ?", (moment, path)).rowcount:
        connection.commit()
        return
    connection.execute(
        "INSERT INTO files(path, inode, size, mtime_ns, offset, state, attempted) VALUES(?,?,?,?,0,'{}',?)",
        (path, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, moment))
    connection.commit()


def _resume(connection, path, metadata):
    row = connection.execute("SELECT inode, offset, state FROM files WHERE path = ?", (path,)).fetchone()
    if not row or row[0] != metadata.st_ino:
        return 0, 0, {}
    try:
        state = json.loads(row[2])
    except ValueError:
        state = None
    if not isinstance(state, dict):
        return 0, 0, {}
    skip = state.pop("_skip", 0)
    if not isinstance(skip, int) or skip < 0 or metadata.st_size < row[1] + skip:
        return 0, 0, {}
    return row[1], skip, state


def _lines(handle, limit, budget, progress):
    skipping = progress["skip"] > 0
    while budget[0] > 0:
        room = min(limit + 1, budget[0])
        line = handle.readline(room)
        if not line:
            return
        budget[0] -= len(line)
        if line.endswith(b"\n"):
            if skipping:
                skipping = False
                progress["skip"] = 0
            elif len(line) <= limit:
                progress["offset"] = handle.tell()
                yield line
                continue
            progress["offset"] = handle.tell()
            yield None
            continue
        if skipping:
            progress["skip"] += len(line)
            continue
        if len(line) < room:
            return  # trailing partial line; it waits for the next run
        if room <= limit:
            return  # budget cut the line; it is re-read next run
        skipping = True
        progress["skip"] = len(line)


def _forget_missing(connection) -> None:
    paths = [row[0] for row in connection.execute("SELECT path FROM files")]
    for path in paths:
        if not os.path.exists(path):
            connection.execute("DELETE FROM files WHERE path = ?", (path,))
    connection.commit()


def _write_event(connection, provider, event, merge) -> None:
    values = (event["key"], event["ts"], provider, event.get("session") or "", event.get("model") or "",
              int(event.get("input") or 0), int(event.get("cache_read") or 0), int(event.get("cache_write") or 0),
              int(event.get("output") or 0), int(event.get("reasoning") or 0))
    verb = "INSERT OR REPLACE INTO events" if merge is None else "INSERT INTO events"
    suffix = "" if merge is None else " " + merge
    connection.execute(verb + "(key, ts, provider, session, model, input, cache_read, cache_write, output, reasoning)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?)" + suffix, values)
