# Tokens used and models used (local usage details)

## Goal

Show, per provider, how many tokens have been used and which models were
used — as a complement to the existing subscription percentages, not a
replacement. All figures come from local files the coding tools already
write; no new endpoints, credentials, or network calls.

Explicit non-goals: cost estimates (stale pricing tables are a maintenance
trap — OpenCode's log is the only source with an exact per-message cost),
token-level detail below model granularity, and any change to the
percentage/reset behavior the plugin exists for.

## What is available, per provider

Audited on this machine 2026-10-12. All three sources are live and parseable
with stdlib only.

| Provider | Source | Tokens | Models | Notes |
| --- | --- | --- | --- | --- |
| Claude Code | `~/.claude/projects/<project>/<session>.jsonl` | `message.usage`: input, output, cache read/write, thinking | `message.model` per assistant message | 155 MB / 155 files here; entries can repeat across resumed sessions |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | `event_msg/token_count` cumulatives per session (input, cached, output, reasoning, total) | `turn_context.model` (e.g. `gpt-6.1-sol`) | 387 MB / 236 files here; `token_count` is cumulative, sum deltas or last value per session |
| OpenCode | `~/.local/share/opencode/opencode.db` (SQLite, `message.data` JSON) | `tokens.total/input/output/reasoning/cache` | `modelID` / `providerID` | also carries `cost` per message if ever wanted; read-only (`mode=ro`) |
| Cursor | `~/.cursor/ai-tracking/ai-code-tracking.db` | none found — DB tracks AI code attribution and commit scoring | `model`, `conversationId` only | Cursor's token detail appears to be server-side only; audit the dashboard API response before promising anything |
| Grok | no local directory present | — | — | nothing to read today |
| Antigravity | no local directory present | — | — | nothing to read today |
| Z.ai | quota endpoint returns `TOKENS_LIMIT`/`CREDIT_LIMIT` with `currentValue`/`usage` | quota quantities, not request tokens | — | the API reports percent-used; raw token counts are not exposed |

Rule: a provider without a parseable local source simply shows no details
section. Never a zero that reads as "you used nothing".

## Design

### Incremental offline scan (the load-bearing part)

A full walk of ~540 MB of logs on every refresh (default 5 minutes) is not
acceptable. `usage.py` gets a small scan-state file (sibling of the plugin's
other local data) with per-file `mtime`, size, and byte offset:

- Read from the stored offset; process only complete lines (keep a
  remainder for the next pass).
- File truncated or rotated → reset that file's offset.
- Keep at most N tracked files (LRU); ignore files older than the display
  window (e.g. > 8 days) and remove their state entries.
- Claude Code's own cleanup deletes old JSONLs; state must tolerate
  disappearing files silently.

Aggregates are computed per model and per provider over a rolling window
(today + last 7 days), then folded into the collector JSON. The scan runs
only for enabled providers, alongside the existing per-provider collect.

### Output shape

Add to each row, only when a local source exists:

```json
"details": {
  "source": "local-logs",
  "windowDays": 7,
  "tokens": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
  "models": [{"name": "gpt-6.1-sol", "tokens": 0, "messages": 0}]
}
```

Numbers are exact; percent stays the quota number. Keep both visible so
"41% of the session used, 2.3M tokens this week" never collapses into one
ambiguous figure.

### UI

- **Panel provider card** (`Panel.qml`): an optional compact details block
  under the metrics — one line like `2.3M tokens this week · top models:
  opus-4-5 61%, haiku-5 27%`. Hidden entirely when absent. Sources are
  labeled "local logs" once, in the settings legend, so users know this is
  attribution data (their machine's record), not provider-billed data.
- **Settings** (`Settings.qml`): one toggle, "Local token details"
  (default on), covering the panel block. No per-provider knobs in v1.
- **Navbar**: unchanged. The bar is full; tokens are a drill-down.
- **CLI**: `--pretty` already exposes the details for debugging; no new
  flags.

## Risks

- **Performance**: the whole feature is the incremental scanner. Without
  offsets it is dice. Test with a cold scan vs. warm scan (target: warm
  refresh well under a second of I/O for typical logs).
- **Format drift**: Claude and Codex JSONL are internal formats and will
  change. Parsers must be tolerant (skip unknown, count what parses) and a
  provider whose logs stop parsing degrades to "no details", never to an
  error row.
- **Time-window semantics**: logs have timestamps; quotas don't share
  their windows. Say "last 7 days (local)" explicitly, never imply it
  matches the provider's weekly limit.
- **Cursor trap**: its local DB looks like it has model data but has no
  tokens. Exclude until the dashboard API is audited; do not ship an
  attribution-derived number as usage.
- **Privacy**: only known paths are read; never crawl. Log contents can
  include prompts — parse numbers and model names only, never retain or
  emit other fields.

## Testing

- Claude/Codex JSONL fixtures with redacted lines; offset/rotation/
  truncation cases; duplicate-entry handling for resumed Claude sessions.
- OpenCode: temp SQLite built with stdlib `sqlite3` in the test setup.
- Missing files, empty files, unreadable files, giant single-line files.
- Suspend/resume: log written while plugin collected — no double counting
  after the next refresh.

## Phases

1. Scanner + `usage.py --pretty` output; Claude, Codex, OpenCode. Fixtures
   and incremental-state tests. No UI.
2. Panel details block + settings toggle; README updates (privacy table
   gets the log paths, provider table gets a "Local usage" column).
3. Audit Cursor API for token fields; decide on Grok/Antigravity local
   sources if their CLIs start writing logs.

## Open questions

- Window: fixed 7 days, or follow the selected display window (session/
  weekly) when one exists? Start fixed; the quota reset countdown already
  answers "when do I get more".
- Should the details block merge with the future history/sparkline work
  (plans would share the same per-file state and window), or stay separate
  until that lands?
