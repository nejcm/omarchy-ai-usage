# Tokens used and models used (local usage tab)

## Goal

A **Usage** tab next to the existing limits view that shows how many tokens
this machine's coding tools used and on which models. It complements the
quota percentages, never replaces them. All figures come from local files the
tools already write: no new endpoints, credentials, or network calls.

Non-goals:

- **Cost.** Pricing tables go stale and a subscription is not API spend.
  OpenCode's per-message cost alone would make a misleading partial total.
- **Pretty model names.** Same staleness problem as pricing.
- **Activity calendar and hours-of-week heatmaps.** They need more than 30
  days of history or hourly buckets, which is extra state for little value.
- **Per-project and top-session lists.** Project paths and session titles
  come from prompt content and would break the privacy rule below.
- **"Plan capacity" (tokens per quota window).** It divides local tokens by
  quota percentages over windows that don't line up, which is exactly the
  ambiguity this plan avoids.
- **Provider filter chips.** With three sources, the by-provider list and the
  stacked bars already split the totals.
- **Navbar changes.** The bar stays quota-only.

References: `examples/hero.png` (Limits/Costs tabs, by-day stacked bars, model
breakdown) and `examples/preview.png` (summary row, by-provider/by-model bar
lists, token breakdown). Parsing approach borrowed from
[omarchy-quotatank](https://github.com/JanitorHead/omarchy-quotatank)
(`scripts/cost-fetch.py`) and
[BF-Agent-Ledger](https://github.com/BeforeUgone123/BF-Agent-Ledger)
(`bin/usage-index`).

## Sources

Audited on this machine 2026-10-13.

| Provider | Source | Volume (≤30 d) | Notes |
| --- | --- | --- | --- |
| Claude Code | `$CLAUDE_CONFIG_DIR` or `~/.claude/projects/**/*.jsonl` | 157 MB / 170 files | resumed sessions copy earlier lines into new files |
| Codex | `$CODEX_HOME` or `~/.codex/{sessions,archived_sessions}/**/*.jsonl` | 416 MB / 264 files | `input_tokens` includes cached tokens |
| OpenCode | `opencode.db` (path via `providers/opencode.data_directory`) | 1,183 messages, 0.01 s query | 2.5 GB db; open with `mode=ro` |
| Cursor | `~/.cursor/ai-tracking/ai-code-tracking.db` | — | no token fields; excluded until the dashboard API is audited |
| Grok, Antigravity, Z.ai | — | — | no local token source today |

A provider without a parseable source does not appear in the tab. Never show
a zero that reads as "you used nothing".

## Parsing

All token buckets are disjoint: `input` (uncached), `cache_read`,
`cache_write`, `output` (excluding reasoning) and `reasoning`.

**Claude.** Keep lines with `type == "assistant"` and skip the model
`<synthetic>`. From `message.usage` read `input_tokens`,
`cache_read_input_tokens` and `cache_creation_input_tokens`. Thinking
(`output_tokens_details.thinking_tokens`, when present) is split out of
`output_tokens` into reasoning. The model is `message.model` and the
timestamp is the top-level `timestamp`. The key is
`claude:{message.id}:{requestId}` and is global across files, so resumed
sessions are not double counted.

**Codex.**

- The model comes from `turn_context.payload.model`, and the session id from
  `session_meta`.
- Usage comes from `event_msg/token_count` `payload.info.last_token_usage`
  per response. Do not take deltas of `total_token_usage`.
- Skip a notification whose `(last, total)` pair repeats the previous one.
- Suppress the replayed `token_count` burst in forked or subagent sessions
  (`forked_from_id` / `source.subagent`).
- Normalize: `input -= cached_input_tokens` and
  `output -= reasoning_output_tokens`.
- The key is `codex:{session}:{byte offset}`, which is stable across
  reparses.

**OpenCode.**

- Select `role = 'assistant'` rows from the window and read `json_extract`
  of `modelID` and `tokens.{input, output, reasoning, cache.read,
  cache.write}`.
- The key is `opencode:{message id}`, written with `INSERT OR REPLACE`
  because token counts change after a row is created.
- There are no offsets. Re-query the window on each run, but skip the query
  while the `[mtime_ns, size]` of the db and its `-wal` are unchanged.
- Attribution is by tool: every message counts as OpenCode, including models
  used with the user's own keys.

**Model IDs.** Show raw IDs and strip a trailing date suffix, so
`claude-opus-5-5-20260101` merges with `claude-opus-5-5`.

**Privacy and speed.**

- Before `json.loads`, check each line for its target substring: `"usage"`
  for Claude, `token_count` or `turn_context` for Codex. Lines with only
  prompt content are never decoded.
- Skip lines over 16 MiB.
- Read only numbers, model IDs, timestamps and ids, and never store other
  fields.
- Read only the known paths and never crawl.

## State

A stdlib `sqlite3` database at `$XDG_CACHE_HOME/omarchy-ai-usage/usage.db`
(default `~/.cache/…`), next to the existing `omarchy-ai-usage.json` cache.

```sql
files(path PRIMARY KEY, inode, size, mtime_ns, offset, state)  -- state: parser JSON (Codex model, last signature, fork state)
events(key PRIMARY KEY, ts, provider, session, model, input, cache_read, cache_write, output, reasoning)
```

- Seek to the stored `offset` and parse only complete lines. A trailing
  partial line waits for the next run.
- If the inode changed or the size dropped below the offset, restart that
  file at 0. The event keys make a reparse idempotent, so no tail-hash guard
  is needed.
- Discovery skips files whose mtime is older than 31 days. Rows for files
  that are gone are dropped, and so are events older than 31 days
  (`DELETE WHERE ts < …`).
- A run reads at most 256 MB of new log bytes. The cold scan (~570 MB here)
  completes over 2–3 refreshes.
- The database is a cache: deleting it costs one cold scan, nothing else.

## Collector

`usage.py --usage` is a separate invocation from the quota collect. It has its
own `Process` and timeout in `BarWidget.qml`, so a slow scan never eats into
the 60 s quota budget (`BarWidget.qml:194`). It runs after each quota refresh
while the setting is on, whether or not the panel is open. It only scans
providers that are enabled.

Output is already aggregated, so QML only renders:

```json
{
  "usage": {
    "scanning": false,
    "windows": {
      "today": { "...": "same shape as 7d, days omitted" },
      "7d": {
        "tokens": 0, "output": 0, "sessions": 0, "cacheHit": 0.0,
        "breakdown": {"input": 0, "cacheRead": 0, "cacheWrite": 0, "output": 0, "reasoning": 0},
        "providers": [{"id": "claude", "tokens": 0}],
        "models": [{"name": "claude-opus-5-5", "provider": "claude", "tokens": 0}],
        "days": [{"date": "2026-10-13", "providers": {"claude": 0}}]
      },
      "30d": {}
    }
  }
}
```

- `tokens` = input + output + reasoning. Cache tokens never go into the
  headline.
- `cacheHit` = cache_read ÷ (input + cache_read + cache_write).
- Today, 7D and 30D are bucketed by local date in SQL at query time, so a
  change of timezone or DST needs no rebucketing.
- `scanning: true` means the cold scan has not finished yet.

## UI

**Panel** (`Panel.qml`): tabs **Limits | Usage**. The panel always opens on
Limits, and the Limits tab is unchanged.

Usage tab, top to bottom:

1. A window selector (**Today / 7D / 30D**, default 7D), persisted in plugin
   settings.
2. A summary row: tokens · output · sessions · cache hit %.
3. By-day bars, stacked per provider. Hidden on Today. Axis labels show the
   first date, the middle date and "now".
4. Tokens by tool: a bar list with a color dot per provider.
5. Tokens by model: the top 5, then "N more". One row per (model, provider),
   with the provider shown as a subtitle.
6. A token breakdown, collapsed by default: input, cache read, cache write,
   output and reasoning, each with its share.

A footer says "Local logs · last N days", never implying the window matches a
provider's quota window. While `scanning` is true, the tab shows "Scanning
local logs…".

**Colors**: one fixed color per provider in `Model.js` (Claude orange, Codex
green, OpenCode purple), chosen so they don't clash with the quota green,
orange and red from `usageColor`.

**Settings** (`Settings.qml`): one toggle, "Local token usage", default on.
Off hides the tab and stops the scan entirely.

## Risks

- **Format drift**: the Claude and Codex JSONL formats are internal. Parsers
  skip unknown lines and count what parses. A source that stops parsing
  drops out of the tab instead of producing an error.
- **Codex forks**: the burst-suppression rule follows quotatank and has not
  been seen on this machine yet. Cover it with a fixture.
- **Claude cleanup**: Claude Code deletes old JSONLs. Events already in the
  db survive until they age out, but after a cache reset the 30D figure can
  be short. That is acceptable for a local view.
- **The cache-read share is dominant**: this is why it stays out of the
  headline.

## Testing

- **Claude fixtures**: redacted lines, a duplicate `message.id`/`requestId`
  spread across two files, a `<synthetic>` model, and thinking tokens.
- **Codex fixtures**: a repeated `(last, total)` pair, a forked-session
  replay burst, and cached and reasoning subtraction.
- **OpenCode**: a temp SQLite db built in the test setup, including a row
  whose tokens are updated after insert, and a check that an unchanged db
  and `-wal` skip the query.
- **State**: a partial trailing line; an append then a rescan with no double
  count; a truncated file and a replaced inode; a deleted file; pruning past
  31 days; the 256 MB budget spreading a cold scan over several runs.
- **Edge cases**: missing, empty and unreadable files, and an oversized
  line.
- **Windows**: local-date bucketing around midnight.

## Phases

Each phase is one commit or PR. It ends green (`python3 -m unittest`, plus the
QML tests from phase 6 on), and nothing user-visible ships before phase 6.
Each phase lists the test cases from **Testing** that it owns.

### 1. State and scan loop

- New module `usage_scan.py` with the SQLite schema, file discovery
  (31-day mtime cutoff), and offset resume with a remainder for a partial
  last line.
- Inode and size reset, removal of rows for deleted files, pruning of events
  older than 31 days, and the 256 MB budget per run.
- Each provider is a parser hook. It takes a line and the per-file state and
  returns events. The first parser is a stub used only by the tests.
- Tests: the **State** and **Edge cases** groups.
- Done when an append followed by a rescan never double counts.

### 2. Claude parser

- The substring check, assistant-only lines, `<synthetic>` skipped,
  thinking tokens split into reasoning, and the global
  `message.id:requestId` key.
- Tests: the Claude fixtures.
- Done when running against the real `~/.claude/projects` finishes within
  the byte budget across runs, and a warm run takes under 1 s.

### 3. Codex parser

- `last_token_usage`, skipping a repeated `(last, total)` pair, fork-burst
  suppression, subtraction of cached and reasoning tokens, `archived_sessions`,
  and the parser state persisted in `files.state`.
- Tests: the Codex fixtures.

### 4. OpenCode source

- A read-only re-query of the window with `INSERT OR REPLACE`, skipped while
  the `[mtime_ns, size]` of the db and its `-wal` are unchanged.
- Tests: the OpenCode group.

### 5. Aggregation and CLI

- `usage.py --usage [--pretty] [--provider …]` emits the `usage` JSON
  described in **Collector**.
- Today, 7D and 30D are computed in SQL with local-date bucketing. Covers
  `tokens`, `cacheHit`, `sessions`, providers, models (date suffix
  stripped), days and `scanning`.
- Tests: the **Windows** group, plus a golden JSON output from a fixtures
  home.
- Done when `--pretty` output checked by hand against this machine's logs
  looks plausible: totals in the right order of magnitude, and the model
  list matches what was actually used.

### 6. Wiring and settings

- A second `Process` in `BarWidget.qml` with its own timeout, run after each
  quota refresh while the setting is on. Its result is kept on the widget,
  not in the quota cache.
- The "Local token usage" toggle in `Settings.qml`, the persisted window
  setting, and the provider colors in `Model.js`.
- Tests: QML tests for the toggle (off means no process runs) and for the
  default window.

### 7. Usage tab

- The Limits | Usage tabs in `Panel.qml`, with the panel always opening on
  Limits.
- The window selector, summary row, by-day stacked bars (hidden on Today),
  the tool and model bar lists, the collapsed breakdown, the scanning state
  and the footer.
- Done when it has been checked in the running panel with real data at the
  default panel width.

### 8. Docs

- README: the privacy table gets the log paths and the db path, the provider
  table gets a "Local usage" column, and a new screenshot.

### 9. Follow-ups (not scheduled)

- Audit Cursor's dashboard API for token fields.
- Add Grok or Antigravity sources if their CLIs start writing local logs.
