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
panel opens while the cache is stale, and at most every five minutes (the
interval has a hard 300-second floor). The collector reads each provider's
local credential file, calls that provider's one quota endpoint, and prints a
normalized JSON document. The widget merges by provider, so a failed refresh
keeps that provider's last good metrics and successful timestamp and marks the
row `stale` instead of erasing it.

`usage.py` is standard-library only: no daemon, no extra packages. Credentials
stay in memory and are used only in the `Authorization` header of the
provider's own endpoint. Tokens never appear in stdout, stderr, process
arguments, or logs. The one persisted secret is Claude Code's rotated OAuth
token, described below.

## Providers

| Provider | Credential file read | Host contacted | Window(s) |
|---|---|---|---|
| Claude Code | `~/.claude/.credentials.json` (`CLAUDE_CONFIG_DIR`) | `api.anthropic.com`, `platform.claude.com` | Session (5h), Weekly (7d) |
| Codex | `~/.codex/auth.json` (`CODEX_HOME`) | `chatgpt.com` | Session, Weekly |
| OpenCode | `~/.local/share/opencode/auth.json` (`XDG_DATA_HOME`, `OPENCODE_DATA_DIR`) | `opencode.ai` | Session, Weekly, Monthly |
| Cursor | `~/.config/cursor/auth.json` (`XDG_CONFIG_HOME`) | `api2.cursor.sh` | Total usage, Cursor models, Other models |

Each provider is one module under `providers/` that declares its credential
path, allowed hosts, fetch, and response parser. Adding a provider is one new
module, its fixtures, and one line in `providers/__init__.py`.

The shared transport in `usage.py` enforces a per-provider host allow-list, a
10-second timeout, no HTTP redirects (so an `Authorization` header is never
forwarded to another host), and bounded status/error codes
(`not-signed-in`, `expired`, `unavailable`, `rate-limited`, `error`). HTTP
error bodies are discarded, so nothing sensitive can leak through an error.

## Claude OAuth refresh (the one persisted secret)

When Claude Code's access token is expired — or the usage call returns 401 —
the collector POSTs the refresh token to
`https://platform.claude.com/v1/oauth/token` and uses the rotated access
token. The whole rotation runs under Claude Code's own refresh lock
(`~/.claude/.oauth_refresh.lock`, the same directory lock `proper-lockfile`
uses with a 60-second stale window): the credential file is re-read under the
lock, and if another process already rotated it the new value is adopted
instead of refreshed. If the lock is already held, no refresh is attempted and
the row reads `refresh-locked` (shown as stale with the last good values).

The collector publishes an empty directory it already owns using Linux
`renameat2(RENAME_NOREPLACE)`, then updates its mtime through its descriptor
every five seconds during the exchange. It never removes the shared lock,
including stale locks. On release it stops and joins the heartbeat and marks
only its owned directory stale. Claude Code reclaims it; until then another
collector refresh returns `refresh-locked`.

The exchange runs in a child process with a 20-second deadline and up to one
second for cancellation. The child is killed if necessary and always reaped
before lock release. A completed response is recovered from anonymous memory
and persisted even if the child exits after the deadline. `refresh-timeout`
means no complete response was recovered; the server may already have rotated
the token, so run Claude Code to recover the login rather than retrying here.

A successful rotation is written back to `~/.claude/.credentials.json`: all
other keys are preserved, the write is a temp file in the same directory at
mode `0600` followed by `os.replace`, and the whole `claudeAiOauth` object is
compared, and ownership is checked immediately before replacement. Ownership
loss returns `lock-lost` without replacing credentials. If the write fails the
row is an error (`persist-write-failed`), never `ok`. This is the only token
this plugin ever persists; it is never logged or passed on the command line.
An invalid refresh expiry is ignored while the rotated tokens are saved.

## Status behavior

- `not-signed-in` — no credential file, no usable token, or a Claude refresh
  rejected with `invalid_grant`.
- `expired` — a token is past its own expiry and could not be refreshed (for
  example Codex or Cursor, whose rotation is owned by their CLI and not
  written here). Run the CLI once to refresh its login.
- `stale` — the last refresh failed; the previously fetched metrics are kept.
- `unavailable` — a valid credential with no quotable subscription (for
  example a Codex API key instead of an OAuth login, or an OpenCode key with
  no Go plan).
- `rate-limited` — the provider returned HTTP 429.
- `error` — malformed credential storage or response, or a network failure,
  with the bounded code in the panel.

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
