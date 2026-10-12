.pragma library

// Pure formatting, provider-selection, and merge helpers for the widget and panel.

var PROVIDER_INFO = {
  claude: { name: "Claude Code", logo: "claude", mono: false, cli: "claude" },
  codex: { name: "Codex", logo: "chatgpt", mono: true, cli: "codex" },
  opencode: { name: "OpenCode", logo: "opencode", mono: false, cli: "opencode" },
  cursor: { name: "Cursor", logo: "cursor", mono: true, cli: "cursor-agent" },
  grok: { name: "Grok", logo: "grok", mono: true, cli: "grok" },
  antigravity: { name: "Antigravity", logo: "antigravity", mono: false, cli: "agy" },
  zai: { name: "Z.ai", logo: "z.ai", mono: true, cli: "chelper" }
}
var PROVIDERS = Object.keys(PROVIDER_INFO)
var REFRESH_MINUTES = [1, 2, 3, 5, 10, 15, 30, 60]
var DEFAULT_ENABLED = ["claude", "codex"]
var TROUBLESHOOTING_URL = "https://github.com/nejcm/omarchy-ai-usage#troubleshooting"
var SETTING_DEFAULTS = {
  providerOrder: [],
  enabledProviders: DEFAULT_ENABLED,
  hiddenProviders: [],
  refreshIntervalSec: 300,
  displayMode: "used",
  warningThreshold: 80,
  colorWarnings: true,
  desktopNotifications: false
}

function providerList(value) {
  return value && typeof value === "object" && typeof value.length === "number" ? Array.prototype.slice.call(value) : []
}

function resetSettings(settings) {
  return Object.assign({}, settings || {}, SETTING_DEFAULTS)
}

function moveItem(list, id, target) {
  var order = providerList(list).slice()
  var index = order.indexOf(id)
  if (index < 0) return order
  target = Math.max(0, Math.min(order.length - 1, target))
  if (target === index) return order
  order.splice(index, 1)
  order.splice(target, 0, id)
  return order
}

function enabledInOrder(order, enabled) {
  var list = providerList(enabled)
  return order.filter(function(id) { return list.indexOf(id) >= 0 })
}

function providerOrder(saved) {
  var order = []
  var requested = providerList(saved)
  for (var i = 0; i < requested.length; i++) {
    if (PROVIDERS.indexOf(requested[i]) >= 0 && order.indexOf(requested[i]) < 0) order.push(requested[i])
  }
  for (var j = 0; j < PROVIDERS.length; j++) {
    if (order.indexOf(PROVIDERS[j]) < 0) order.push(PROVIDERS[j])
  }
  return order
}

function selectedProviders(order, hidden) {
  var list = providerList(hidden)
  return order.filter(function(id) {
    return list.indexOf(id) < 0
  })
}

function orderedRows(rows, ids) {
  var out = []
  for (var i = 0; i < ids.length; i++) {
    for (var j = 0; j < rows.length; j++) if (rows[j].provider === ids[i]) out.push(rows[j])
  }
  return out
}

function refreshSeconds(value) {
  var seconds = Number(value)
  return REFRESH_MINUTES.indexOf(seconds / 60) >= 0 ? seconds : 300
}

function warningThreshold(value) {
  var number = Number(value)
  return isFinite(number) ? Math.max(1, Math.min(100, Math.round(number))) : 80
}

var STATUS = {
  "stale": "stale",
  "not-signed-in": "not signed in",
  "expired": "sign-in expired",
  "unavailable": "unavailable",
  "rate-limited": "rate limited",
  "error": "error"
}

// Plain-language text for the bounded collector error codes; unknown codes keep the raw form.
var ERROR_TEXT = {
  "auth-expired": "Sign-in expired",
  "invalid-grant": "Sign-in rejected",
  "http-401": "Sign-in expired",
  "http-403": "Sign-in expired",
  "http-429": "Rate limited",
  "network": "Network error",
  "timeout": "Request timed out",
  "host-not-allowed": "Blocked provider host",
  "invalid-auth": "Invalid credentials",
  "invalid-request": "Invalid request",
  "unreadable": "Credentials unreadable",
  "malformed-auth": "Credentials unreadable",
  "malformed-response": "Malformed provider response",
  "no-data": "No subscription data",
  "api-key-auth": "API key sign-in unsupported",
  "no-subscription": "No subscription found",
  "no-coding-plan": "No coding plan found",
  "refresh-locked": "Refreshing elsewhere",
  "refresh-failed": "Refresh failed",
  "refresh-rejected": "Sign-in refresh rejected",
  "refresh-timeout": "Sign-in refresh timed out",
  "reread-failed": "Credentials could not be re-read",
  "persist-changed": "Credentials changed during refresh",
  "persist-unreadable": "Credentials unreadable",
  "persist-write-failed": "Could not save refreshed sign-in",
  "persist-lock-lost": "Credential lock lost during refresh",
  "write-failed": "Could not save credentials",
  "lock-lost": "Credential lock lost",
  "exchange-failed": "Sign-in refresh interrupted",
  "internal-error": "Collector error",
  "not-signed-in": "Not signed in",
  "unavailable": "Unavailable",
  "rate-limited": "Rate limited",
  "expired": "Sign-in expired",
  "stale": "Stale"
}

var SIGN_IN_ERRORS = ["auth-expired", "invalid-grant", "http-401", "http-403"]

function logo(provider, white) {
  var info = PROVIDER_INFO[provider]
  return info ? info.logo + (white ? ".white" : "") + ".svg" : ""
}

function panelLogo(provider) {
  var info = PROVIDER_INFO[provider]
  return logo(provider, info && info.mono)
}

function hasData(row) {
  return !!row && (row.status === "ok" || row.status === "stale")
}

function primaryPercent(row) {
  if (!hasData(row) || !row.metrics || row.metrics.length === 0) return null
  var best = null
  for (var i = 0; i < row.metrics.length; i++) {
    if (row.metrics[i].percent === null || row.metrics[i].percent === undefined) continue
    var value = Number(row.metrics[i].percent)
    if (isNaN(value)) continue
    if (best === null || value > best) best = value
  }
  return best
}

function barValue(row, mode) {
  var used = primaryPercent(row)
  if (used === null) return percentText(null)
  var remaining = 100 - Math.round(used)
  if (mode === "remaining") return percentText(remaining)
  if (mode === "both") return percentText(used) + " / " + percentText(remaining)
  return percentText(used)
}

function barTooltip(mode) {
  var basis = mode === "remaining" ? "percent remaining of each provider's most-restricted limit"
    : mode === "both" ? "percent used and remaining of each provider's most-restricted limit"
    : "percent used of each provider's most-restricted limit"
  return "AI usage \u2014 " + basis
}

function isWarning(row, threshold) {
  var value = primaryPercent(row)
  return value !== null && value >= threshold
}

function warningEvents(rows, previous, threshold, notify) {
  var state = Object.assign({}, previous || {})
  var events = []
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i]
    if (row.status !== "ok") continue
    for (var j = 0; j < row.metrics.length; j++) {
      var metric = row.metrics[j]
      if (metric.percent === null || metric.percent === undefined || !isFinite(Number(metric.percent))) continue
      var key = row.provider + ":" + metric.label
      var period = isNaN(Date.parse(metric.resetsAt)) ? "" : metric.resetsAt
      var old = state[key]
      // Relative reset estimates can drift between polls.
      var samePeriod = !!old && (old.period === period || Math.abs(Date.parse(old.period) - Date.parse(period)) < 60000)
      if (samePeriod) period = old.period
      var fired = samePeriod && old.fired === true
      if (!period && Number(metric.percent) < threshold) fired = false
      if (notify && Number(metric.percent) >= threshold && !fired) {
        events.push({ name: row.name, label: metric.label, percent: metric.percent })
        fired = true
      }
      state[key] = { period: period, fired: fired }
    }
  }
  return { state: state, events: events }
}

function planText(row) {
  return row && row.plan ? row.plan : ""
}

function statusText(row) {
  if (!row || row.status === "ok") return ""
  if (row.error && ERROR_TEXT[row.error]) return ERROR_TEXT[row.error]
  var label = STATUS[row.status] || row.status
  return row.error ? label + " (" + row.error + ")" : label
}

function statusDetail(row) {
  if (!row || row.status === "ok") return ""
  var label = STATUS[row.status] || row.status
  return row.error ? label + " (" + row.error + ")" : label
}

function statusHint(row) {
  if (!row) return ""
  var cli = providerCli(row.provider)
  if (cli && (row.status === "not-signed-in" || row.error === "not-signed-in")) return "Sign in with " + cli + " to connect"
  if (cli && (row.status === "expired" || SIGN_IN_ERRORS.indexOf(row.error) >= 0)) return "Open " + cli + " to renew sign-in"
  if (row.status === "rate-limited" || row.error === "http-429") return "Raise the refresh interval"
  if (row.error === "refresh-locked") return "Retrying on the next update"
  if (cli && row.error === "refresh-timeout") return "Open " + cli + " to recover the sign-in"
  return ""
}

function providerCli(provider) {
  var info = PROVIDER_INFO[provider]
  return info && info.cli ? info.cli : ""
}

function needsSignIn(row) {
  if (!row) return false
  if (row.status === "not-signed-in" || row.status === "expired") return true
  return row.error === "not-signed-in" || SIGN_IN_ERRORS.indexOf(row.error) >= 0
}

function connectHint(row) {
  return needsSignIn(row) ? statusHint(row) : ""
}

function anyNeedsSignIn(rows) {
  var list = rows || []
  for (var i = 0; i < list.length; i++) if (needsSignIn(list[i])) return true
  return false
}

// Keep the last good metrics and timestamp when a provider now fails.
function mergeRows(previous, incoming) {
  var byId = {}
  var prior = previous || []
  for (var i = 0; i < prior.length; i++) byId[prior[i].provider] = prior[i]
  var out = []
  var next = incoming || []
  for (var j = 0; j < next.length; j++) {
    var row = next[j]
    var old = byId[row.provider]
    if (row.status !== "ok" && hasData(old)) {
      out.push({
        provider: row.provider,
        name: row.name,
        abbrev: row.abbrev,
        plan: old.plan,
        status: "stale",
        error: row.error || row.status,
        metrics: old.metrics,
        resetAt: old.resetAt,
        refreshedAt: old.refreshedAt
      })
    } else {
      out.push(row)
    }
  }
  return out
}

function markStale(rows) {
  var out = []
  var list = rows || []
  for (var i = 0; i < list.length; i++) {
    var row = list[i]
    if (row.status !== "ok") {
      out.push(row)
    } else {
      out.push({
        provider: row.provider,
        name: row.name,
        abbrev: row.abbrev,
        plan: row.plan,
        status: "stale",
        error: "refresh-failed",
        metrics: row.metrics,
        resetAt: row.resetAt,
        refreshedAt: row.refreshedAt
      })
    }
  }
  return out
}

function percentText(value) {
  return value === null || value === undefined || isNaN(value) ? "\u2013" : Math.round(value) + "%"
}

function usageColor(value) {
  return value <= 75 ? "#4ade80" : value <= 90 ? "#fb923c" : "#f87171"
}

function resetText(iso, nowMs) {
  if (!iso) return ""
  var target = Date.parse(iso)
  if (isNaN(target)) return ""
  var now = (nowMs === undefined || nowMs === null) ? Date.now() : nowMs
  var minutes = Math.floor((target - now) / 60000)
  if (minutes <= 0) return "now"
  if (minutes < 60) return minutes + "m"
  var hours = Math.floor(minutes / 60)
  if (hours < 24) return hours + "h " + (minutes % 60) + "m"
  return Math.floor(hours / 24) + "d " + (hours % 24) + "h"
}

function updatedText(iso, nowMs) {
  if (!iso) return ""
  var target = Date.parse(iso)
  if (isNaN(target)) return ""
  var now = (nowMs === undefined || nowMs === null) ? Date.now() : nowMs
  var minutes = Math.floor((now - target) / 60000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return minutes + "m ago"
  var hours = Math.floor(minutes / 60)
  if (hours < 24) return hours + "h ago"
  return Math.floor(hours / 24) + "d ago"
}

function clockText(iso) {
  if (!iso) return ""
  var date = new Date(iso)
  if (isNaN(date.getTime())) return ""
  var hours = date.getHours()
  var minutes = date.getMinutes()
  return (hours < 10 ? "0" : "") + hours + ":" + (minutes < 10 ? "0" : "") + minutes
}
