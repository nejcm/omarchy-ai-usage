"""Aggregate the usage cache into the collector's windowed JSON."""

from __future__ import annotations

from datetime import date, timedelta

WINDOWS = (("today", 0), ("7d", 6), ("30d", 29))
SUMMARY = """
SELECT provider, sum(input + output + reasoning), sum(output + reasoning),
       sum(input), sum(cache_read), sum(cache_write), sum(output), sum(reasoning)
FROM events
WHERE date(ts, 'unixepoch', 'localtime') >= ? AND date(ts, 'unixepoch', 'localtime') <= ?
GROUP BY provider
"""
SESSIONS = """
SELECT DISTINCT provider, session FROM events
WHERE date(ts, 'unixepoch', 'localtime') >= ? AND date(ts, 'unixepoch', 'localtime') <= ?
"""
MODELS = """
SELECT provider, model, sum(input + output + reasoning)
FROM events
WHERE date(ts, 'unixepoch', 'localtime') >= ? AND date(ts, 'unixepoch', 'localtime') <= ?
GROUP BY provider, model
"""
DAYS = """
SELECT date(ts, 'unixepoch', 'localtime'), provider, sum(input + output + reasoning)
FROM events
WHERE date(ts, 'unixepoch', 'localtime') >= ? AND date(ts, 'unixepoch', 'localtime') <= ?
GROUP BY 1, 2
"""


def windows(connection, now, providers=None) -> dict:
    """The today, 7d and 30d windows, aggregated from the cache."""
    connection.execute("BEGIN")
    try:
        return {name: _window(connection, now, span, providers) for name, span in WINDOWS}
    finally:
        connection.execute("COMMIT")


def _window(connection, now, span, providers):
    first = date.fromtimestamp(now) - timedelta(days=span)
    start, end = str(first), str(date.fromtimestamp(now))
    stats = [row for row in connection.execute(SUMMARY, (start, end)) if _wanted(row[0], providers)]
    breakdown = {
        "input": sum(row[3] for row in stats),
        "cacheRead": sum(row[4] for row in stats),
        "cacheWrite": sum(row[5] for row in stats),
        "output": sum(row[6] for row in stats),
        "reasoning": sum(row[7] for row in stats),
    }
    denominator = breakdown["input"] + breakdown["cacheRead"] + breakdown["cacheWrite"]
    models = [{"name": row[1], "provider": row[0], "tokens": row[2]}
              for row in connection.execute(MODELS, (start, end)) if _wanted(row[0], providers)]
    window = {
        "tokens": sum(row[1] for row in stats),
        "output": sum(row[2] for row in stats),
        "sessions": sum(1 for row in connection.execute(SESSIONS, (start, end)) if _wanted(row[0], providers)),
        "cacheHit": breakdown["cacheRead"] / denominator if denominator else 0.0,
        "breakdown": breakdown,
        "providers": sorted(({"id": row[0], "tokens": row[1]} for row in stats),
                            key=lambda entry: (-entry["tokens"], entry["id"])),
        "models": sorted(models, key=lambda entry: (-entry["tokens"], entry["provider"], entry["name"])),
    }
    if span:
        window["days"] = _days(connection, start, end, span, providers, sorted(row[0] for row in stats))
    return window


def _days(connection, start, end, span, providers, ids):
    first = date.fromisoformat(start)
    filled = {(first + timedelta(days=offset)).isoformat(): dict.fromkeys(ids, 0) for offset in range(span + 1)}
    for day, provider, tokens in connection.execute(DAYS, (start, end)):
        if _wanted(provider, providers) and day in filled:
            filled[day][provider] = tokens
    return [{"date": day, "providers": filled[day]} for day in sorted(filled)]


def _wanted(provider, providers) -> bool:
    return providers is None or provider in providers
