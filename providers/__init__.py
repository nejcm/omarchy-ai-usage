"""Provider registry: add one module and one REGISTRY line per provider."""

from __future__ import annotations

from . import antigravity, claude, codex, cursor, grok, opencode

REGISTRY = [claude, codex, opencode, cursor, grok, antigravity]

BY_ID = {module.ID: module for module in REGISTRY}
