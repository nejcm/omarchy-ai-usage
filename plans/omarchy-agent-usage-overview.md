# Omarchy agent usage overview

## Goal

Build a small, local Omarchy plugin that shows subscription quota for the AI coding agents already installed on this machine. A bar widget opens a panel with one row per supported agent, current usage, reset time, and refresh status.

Use Omarchy's user plugin directory and existing Quickshell process. Do not build a separate desktop app or background daemon.

## MVP scope

- Start with Claude Code and Codex. Add OpenCode only if its Linux account exposes a usable quota endpoint during the source audit.
- Show session and weekly usage when the provider reports them, plus reset countdown and last successful refresh.
- Refresh when the panel opens, then at most every five minutes. Show cached values while a refresh runs.
- Show `Not signed in`, `Unavailable`, or `Stale` per provider. One provider failure must not hide the others.
- Read credentials only from the known agent config locations. Keep tokens in memory, send them only to the provider's documented or observed first-party endpoint, and never log them. One exception: Claude Code's rotated OAuth token is written back to `~/.claude/.credentials.json` (atomic, `0600`) because the CLI reuses the stored refresh token; see README.
- No telemetry, account sync, spend estimation, API-key entry, provider actions, or arbitrary endpoint configuration.

## Implementation shape

Create one user-owned Omarchy `bar-widget` plugin with a bar entry and a details panel. The bar shows a compact indicator for providers with usable data; the panel shows the per-provider rows.

Keep provider fetching out of the Quickshell render loop. Use a one-shot Python 3 helper with the standard library for file reads and HTTPS requests; invoke it asynchronously from the plugin. It reads only the named auth/config files, normalizes results to JSON, and exits. No persistent service or extra Python packages. Keep the collector separate from QML so provider parsing can be fixture-tested without launching Omarchy.

Suggested plugin files:

```text
manifest.json
BarWidget.qml
Panel.qml
Model.js
usage.py
tests/fixtures/
tests/test_usage.py
```

The normalized row should contain only `provider`, `plan`, `metrics[]`, `resetAt`, `refreshedAt`, and a bounded status/error code. Do not pass raw provider responses or credentials to the UI.

## Work sequence

1. **Audit local sources.** Confirm which agents are installed and signed in. For Claude Code and Codex, identify the Linux credential files, quota request, and response shape from the current OpenUsage provider implementations and local CLI state. Do not print token values. If a provider needs an undocumented endpoint or an unavailable credential, mark it unsupported for the MVP rather than guessing.
2. **Build the collector.** Implement one provider at a time, with redacted response fixtures and tests for valid, missing, malformed, expired-auth, and rate-limited responses. Add host allow-lists and request timeouts. Ensure errors and debug output cannot include headers or tokens.
3. **Build the Omarchy plugin.** Start from a current built-in bar widget with a panel. Use the Omarchy plugin manifest and user plugin path. Render loading, stale, no-account, error, and quota states without blocking the shell.
4. **Verify on the machine.** Test using fixtures first. Then run against the user's already-authenticated accounts and confirm the displayed quota/reset values match each provider's own CLI or dashboard. Check that logs, process arguments, and cache files contain no credentials. Reload/restart the Omarchy shell only as required by the installed version.
5. **Package for personal use.** Keep it as a local plugin checkout first. Add a README with install, supported providers, credential paths read, network hosts contacted, and known limitations. Consider publishing only after the provider behavior is stable.

## Acceptance criteria

- The widget and panel load through the installed Omarchy plugin system without starting another Quickshell process.
- At least Claude Code and Codex display accurate session and weekly quotas and reset times when signed in.
- Missing auth, network failure, rate limits, and malformed data produce clear per-provider states and preserve the last good value as stale.
- Refresh and provider parsing do not block the shell UI.
- Tests use fixtures and make no provider network calls.
- No secrets are emitted in logs, included in process arguments, or sent to any host outside the provider allow-list. The one persisted secret is Claude Code's rotated OAuth token, written atomically to `~/.claude/.credentials.json` because the CLI requires it; no other token is ever written.

## Risks and limits

- Provider quota endpoints and auth formats can change without notice. Each provider needs a small maintenance test against its current response shape.
- Omarchy plugins run inside the shell with the user's permissions and are not sandboxed. Keep file access narrow and review the full plugin before enabling it.
- If Linux auth is stored in a format the helper cannot safely read, leave that provider unsupported. Do not add token-copying or keychain-compatibility machinery for the MVP.
- A bar has little room for useful detail, so quota percentages belong in the panel; the bar indicator is only a summary.

## Rough effort

About 1–2 focused weeks with AI-assisted implementation, assuming the existing Claude and Codex credentials and quota endpoints work on this machine. The source audit and live verification are the uncertain parts; adding providers later is separate work.

## References

- [OpenUsage provider architecture](https://github.com/robinebers/openusage/blob/main/docs/architecture.md)
- [Omarchy shell plugin development](https://plugins.omarchy.org/develop.html)
- [Omarchy shell plugin contract](https://github.com/basecamp/omarchy/blob/quattro/shell/README.md)
