# AI usage (Omarchy bar plugin)

A small Omarchy `bar-widget` that shows subscription quota for the AI coding
agents already installed on this machine. The bar shows one compact
percentage per provider; the panel shows every plan window with its reset
countdown.

```
C 42 · X 18 · O 7 · U 2
```

`C` Claude Code, `X` Codex, `O` OpenCode, `U` Cursor. A provider that is not
signed in shows `–` in place of a number and explains itself in the panel.

## Install

Symlink this checkout into Omarchy's user plugin directory, then enable it:

```sh
ln -s "$PWD" ~/.config/omarchy/plugins/io.github.nejcm.ai-usage
omarchy plugin enable io.github.nejcm.ai-usage
```

Reload the shell only if the panel does not appear after a re-scan
(`omarchy-shell shell rescanPlugins`). The plugin runs inside the existing
`omarchy-shell` process; it never starts a second Quickshell.

## How it works

`BarWidget.qml` runs `usage.py` with the system `python3` on load, when the
panel opens while the cache is stale, and at most every five minutes. The
collector reads each provider's local credential file, calls that provider's
one quota endpoint, and prints a normalized JSON document. The widget keeps
the last good document in memory and shows it while a refresh runs, so one
provider failing never hides the others.

`usage.py` is standard-library only: no daemon, no extra packages, no state
written to disk. Credentials stay in memory and are used only in the
`Authorization` header of the provider's own endpoint. Tokens never appear in
stdout, stderr, process arguments, or any file.

## Providers

| Provider | Credential file read | Host contacted | Window(s) |
|---|---|---|---|
| Claude Code | `~/.claude/.credentials.json` (`CLAUDE_CONFIG_DIR`) | `api.anthropic.com` | Session (5h), Weekly (7d) |
| Codex | `~/.codex/auth.json` (`CODEX_HOME`) | `chatgpt.com` | Session, Weekly |
| OpenCode | `~/.local/share/opencode/auth.json` (`XDG_DATA_HOME`, `OPENCODE_DATA_DIR`) | `opencode.ai` | Session, Weekly, Monthly |
| Cursor | `~/.config/cursor/auth.json` (`XDG_CONFIG_HOME`) | `api2.cursor.sh` | Total usage, Cursor models, Other models |

Each provider is one module under `providers/` that declares its credential
path, allowed hosts, fetch, and response parser. Adding a provider is one new
module, its fixtures, and one line in `providers/__init__.py`.

The shared transport in `usage.py` enforces a per-provider host allow-list, a
10-second timeout, and bounded status/error codes
(`not-signed-in`, `expired`, `unavailable`, `rate-limited`, `error`). HTTP
error bodies are discarded, so nothing sensitive can leak through an error.

## Status behavior

- `not-signed-in` — no credential file, or no usable token in it.
- `expired` — the stored token is past its own expiry. The collector does not
  refresh tokens: minting one would rewrite the CLI's credential file, which
  this read-only helper never does. Run the CLI (`claude`, `codex`, …) once to
  refresh its login.
- `unavailable` — a valid credential with no quotable subscription (for
  example a Codex API key instead of an OAuth login, or an OpenCode key with
  no Go plan).
- `rate-limited` — the provider returned HTTP 429.
- `error` — malformed credential storage or response, or a network failure,
  with the bounded code in the panel.

Claude Code currently needs an active `claude` login: its access token is
short-lived and only the CLI refreshes it. Until then the row reads
`sign-in expired`.

## Known limitations

- OpenCode 2 can import the `opencode-go` key from `auth.json` into its
  channel SQLite databases. This collector reads `auth.json` only; if that
  file no longer carries the key, the provider reads as not signed in.
- Cursor's token is read from `~/.config/cursor/auth.json` (the CLI/agent
  store). The original Cursor IDE stores it in a VS Code `state.vscdb`; that
  location is not read.
- No spend estimation, account sync, or provider actions. Quota percentages
  and reset times only.

## Tests

```sh
python3 -m unittest discover tests
```

Tests run entirely against redacted fixture payloads and a fake transport;
they make no network calls.
