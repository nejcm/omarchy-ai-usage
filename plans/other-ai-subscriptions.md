## Candidate providers (ranked)

Ranked by demand × feasibility under the plugin's constraints: local file
credentials on Linux (no keyring), first-party JSON quota endpoint, stdlib
only, percent + reset time. Endpoint details sourced from OpenUsage docs
(github.com/robinebers/openusage, docs/providers/*) unless marked.

### 1. GitHub Copilot — highest value, ready to build

- Creds: `~/.config/github-copilot/apps.json` (editor plugin token) or
  `~/.config/gh/hosts.yml` — the latter exists on this machine already.
- Endpoint: `GET api.github.com/copilot_internal/user`, returns
  percent-remaining buckets (AI credits, extra usage, chat, completions).
- Caveats: since June 2026 paid plans meter AI credits; org Business/Enterprise
  seats may return no personal percent (count-only). New host for the
  allow-list: `api.github.com`.

### 2. Grok Build (xAI)

- Creds: `~/.grok/auth.json` after `grok login`.
- Endpoint: `GET cli-chat-proxy.grok.com/v1/billing?format=credits` — weekly
  shared pool + pay-as-you-go cap; `…/v1/settings` for plan name.
- Caveat: access-token refresh is written back to `auth.json`; the plugin
  currently only persists Claude tokens, so a 401 shows sign-in expired unless
  we add a second write-back flow.

### 3. Devin

- Creds: `~/.local/share/devin/credentials.toml` (tomllib is stdlib on 3.11+).
- Endpoint: Connect RPC `GetUserStatus` on `server.codeium.com`; weekly +
  daily quota, remaining→used flip.
- Caveat: Connect-RPC parsing is more code than plain JSON.

### 4. Google Gemini CLI

- Creds: `~/.gemini/oauth_creds.json` (Google OAuth, local file).
- Limits: 60 requests/day free tier; Google AI Pro/Ultra multiply it.
- Caveat: quota endpoint is undocumented/reverse-engineered (Cloud Code
  `cloudcode-pa.googleapis.com`); needs an audit before committing.

### 5. Antigravity (Google IDE)

- Shared Gemini + Claude pools, rolling 5-hour and weekly windows.
- Endpoint: `v1internal:retrieveUserQuotaSummary` on Cloud Code; on macOS
  OpenUsage prefers the running app's local language server.
- Caveat: OAuth refresh + reverse-engineered endpoints; heaviest maintenance
  of the list. Linux credential location needs audit
  (`~/.gemini/antigravity*`).

### 6. Ollama Cloud

- Creds: key left by `ollama login`.
- Tracks monthly credits (or session/weekly on legacy plans).
- Caveat: usage endpoint undocumented; audit first.

### 7. Z.ai (GLM Coding Plan) — conflicts with current scope

- Popular with local CLIs, but needs an API key. The plan explicitly excludes
  API-key entry (plans/omarchy-agent-usage-overview.md); only viable if the
  key is read from the local CLI's stored file and the scope is amended.

### Excluded by design

- OpenRouter and other API credits: pay-as-you-go spend, not subscription
  allowances; also API-key entry.
- Windsurf, Augment, JetBrains AI: credentials live in the system keyring;
  README already documents keyring stores as unsupported.
- Qwen Code, Cline: free or bring-your-own-key, no subscription limit.
- v0, Lovable, Bolt: no local credentials or CLI on the machine.
- ChatGPT / Claude web: same subscriptions already shown via Codex and
  Claude Code.

### On this machine today

Only `~/.config/gh/hosts.yml` is present beyond the four supported providers,
so Copilot (#1) is the only candidate visible immediately; the rest need the
corresponding tool installed and signed in first.
