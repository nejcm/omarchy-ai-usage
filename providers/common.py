"""Provider-agnostic row shape, parsing, and HTTP-status mapping. No network."""

from __future__ import annotations

import base64
import json
import math
import time
from datetime import datetime, timezone

OK = "ok"
NOT_SIGNED_IN = "not-signed-in"
EXPIRED = "expired"
UNAVAILABLE = "unavailable"
RATE_LIMITED = "rate-limited"
ERROR = "error"


class Response:
    """Result of one HTTP call: status plus parsed JSON, or a bounded error."""

    __slots__ = ("status", "data", "error")

    def __init__(self, status: int, data=None, error: str = ""):
        self.status = status
        self.data = data
        self.error = error


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def percent(value) -> float | None:
    """Percent-used as 0..100, or None when unparseable."""
    if value is None:
        return None
    try:
        number = float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(100.0, number))


def reset_iso(value) -> str:
    """An epoch-seconds, epoch-ms, or ISO reset time as UTC ISO, else ''."""
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _epoch_iso(float(value))
    raw = str(value).strip()
    if not raw:
        return ""
    if raw.isdigit():
        return _epoch_iso(float(raw))
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch_iso(seconds: float) -> str:
    if seconds > 1e12:
        seconds /= 1000.0
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return ""


def expires_at_ms(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def is_expired_ms(value) -> bool:
    stamp = expires_at_ms(value)
    return stamp > 0 and stamp <= time.time() * 1000


def jwt_exp(token: str) -> float | None:
    """The `exp` claim of a compact JWT, or None when unreadable."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        if not isinstance(claims, dict):
            return None
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except (IndexError, ValueError, TypeError, json.JSONDecodeError):
        return None


def is_expired_jwt(token: str) -> bool:
    exp = jwt_exp(token)
    return exp is not None and exp <= time.time()


def metric(label: str, pct: float | None, resets_at: str = "") -> dict | None:
    """A metric, or None when the percentage is missing or unparseable."""
    if pct is None:
        return None
    return {"label": label, "percent": pct, "resetsAt": resets_at}


def row(
    provider: str,
    name: str,
    abbrev: str,
    status: str,
    plan: str = "",
    metrics: list | None = None,
    error: str = "",
) -> dict:
    clean = [m for m in (metrics or []) if isinstance(m, dict)]
    resets = [m["resetsAt"] for m in clean if m.get("resetsAt")]
    return {
        "provider": provider,
        "name": name,
        "abbrev": abbrev,
        "plan": plan,
        "status": status,
        "error": error,
        "metrics": clean,
        "resetAt": min(resets) if resets else "",
        "refreshedAt": now_iso(),
    }


def error_row(provider: str, name: str, abbrev: str, code: str, plan: str = "") -> dict:
    return row(provider, name, abbrev, ERROR, plan=plan, error=code)


def status_row(provider: str, name: str, abbrev: str, response: Response, plan: str = "") -> dict:
    """Map an HTTP status to a bounded row: 429 rate-limited, 401/403 expired."""
    if response.status == 0:
        return error_row(provider, name, abbrev, response.error or "network", plan)
    if response.status == 429:
        return row(provider, name, abbrev, RATE_LIMITED, plan=plan, error="http-429")
    if response.status in (401, 403):
        return row(provider, name, abbrev, EXPIRED, plan=plan, error="http-%d" % response.status)
    return error_row(provider, name, abbrev, "http-%d" % response.status, plan)
