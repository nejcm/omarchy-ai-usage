"""Provider registry. Adding a provider means adding one module here and one
line to REGISTRY; each module declares its own credential path, allowed hosts,
fetch, and parse.
"""

from __future__ import annotations

from . import claude, codex, cursor, opencode

REGISTRY = [claude, codex, opencode, cursor]

BY_ID = {module.ID: module for module in REGISTRY}
