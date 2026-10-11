"""Provider registry: add one module and one REGISTRY line per provider."""

from __future__ import annotations

from . import claude, codex, cursor, opencode

REGISTRY = [claude, codex, opencode, cursor]

BY_ID = {module.ID: module for module in REGISTRY}
