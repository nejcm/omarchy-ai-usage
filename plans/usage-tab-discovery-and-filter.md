# Usage tab: model expansion, tool filter, and empty guidance

## Goal

Make all recorded models reachable, let a developer inspect one tool within Today/7D/30D, and tell a new user which tools supply local usage and how to enable them.

## Current behavior and scope

- `LocalUsage.qml` shows only the first five `usageModels`; its “N more” label is inert. It binds the summary, chart, tool/model lists, and token breakdown to one combined `usageWindow`.
- `local_usage/report.py` already returns per-tool token totals, per-model totals, and daily per-tool totals. Its output, session count, cache-hit ratio, and token breakdown exist only as combined values. A UI-only filter would leave those figures wrong.
- `BarWidget.qml` scans logs for enabled providers. Only Claude Code, Codex, and OpenCode have local usage sources (`usage.py`, `README.md`). `Panel.qml` owns the settings navigation; `LocalUsage.qml` currently cannot request it.
- The change reaches `LocalUsage.qml`, `Panel.qml`, `local_usage/report.py`, `tests/tst_local_usage.qml`, `tests/test_local_usage_report.py`, and the local-usage section of `README.md`. Leave quota collection and provider enablement behavior as they are.

## Steps

1. **Expand models.** Add local `modelsExpanded` state in `LocalUsage.qml`. Show five rows by default; make “N more” a keyboard-focusable button that reveals every model and changes to “Show less”. Collapse on window or tool change. Keep the panel's existing scroll behavior for long lists.
2. **Supply complete per-tool totals.** Extend each window in `local_usage/report.py` with a keyed per-provider summary containing tokens, output, sessions, cache hit, and the five breakdown buckets. Derive it from the same snapshot and provider queries already used for the combined window. Keep existing combined fields and JSON shape valid for current consumers.
3. **Filter the whole view.** Add an `All`/Claude Code/Codex/OpenCode selector in `LocalUsage.qml`, limited to enabled local-usage sources. Default to `All`; keep the choice local to the open panel. If its provider becomes disabled, fall back to `All`. For a chosen tool, bind the summary, daily bars, tool and model lists, and token breakdown to that tool's data; compute chart scaling from the visible series. Keep the Today/7D/30D selector independent. Never mix combined summary figures with filtered chart figures.
4. **Guide empty states.** After a completed scan with no data in the last 30 days, replace “No local usage found” with text naming Claude Code, Codex, and OpenCode as supported local sources and a focusable “Open settings” button. Route its activation through a signal from `LocalUsage.qml` to `Panel.qml`'s existing `showSettings(true)`. Preserve distinct scanning and no-enabled-provider messages. When `All` has data but the selected tool does not, say that this tool has no local usage in the last 30 days and offer `All`; do not show onboarding guidance.
5. **Update docs.** Describe the tool selector, expandable model list, and empty-state path in `README.md`.

## Acceptance checks

- QML test with more than five models: initial five, expand all, collapse to five, keyboard activation, and reset after a filter/window change.
- Report test with at least two providers: each provider summary and cache-hit denominator are correct; their additive counts equal the combined window. Existing report consumers still receive the same combined fields.
- QML test for `All` versus one tool across Today/7D/30D: summary, chart, models, and breakdown agree; disabling the selected provider returns to `All`.
- QML test for scanning, no enabled providers, no local logs, and a selected tool with no data; “Open settings” opens the existing settings view.
- Run focused checks: `python3 -m unittest discover -s tests -p test_local_usage_report.py` and `python3 -m unittest discover -s tests -p test_qml.py`.

## Limits

The filter covers local token usage only, not subscription limits. It uses the existing 30-day local-log scope; it does not recover logs that the coding tools have deleted. No new dependency or persistent setting is needed.
