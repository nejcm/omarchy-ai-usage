.pragma library

// Pure formatting, provider-selection, and merge helpers for the widget and panel.

var PROVIDER_INFO = {
  claude: { name: "Claude Code", logo: "claude", mono: false, cli: "claude" },
  codex: { name: "Codex", logo: "chatgpt", mono: true, cli: "codex" },
  opencode: { name: "OpenCode", logo: "opencode", mono: true, cli: "opencode" },
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
  desktopNotifications: false,
  localUsage: true,
  usageWindow: "7d"
}
var USAGE_WINDOWS = ["today", "7d", "30d", "6m", "1y"]
var USAGE_WINDOW_DAYS = { today: 1, "7d": 7, "30d": 30, "6m": 183, "1y": 365 }
var USAGE_PROVIDER_COLORS = { claude: "#d97757", codex: "#10a37f", opencode: "#8b5cf6" }
var USAGE_PROVIDERS = ["claude", "codex", "opencode"]

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
  "lock-lost": "Credential lock lost",
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

function primaryPercent(row, highest) {
  if (!hasData(row) || !row.metrics || row.metrics.length === 0) return null
  var best = null
  var shortest = null
  var shortestWindow = null
  for (var i = 0; i < row.metrics.length; i++) {
    var metric = row.metrics[i]
    if (metric.percent === null || metric.percent === undefined) continue
    var value = Number(metric.percent)
    if (isNaN(value)) continue
    if (best === null || value > best) best = value
    var minutes = Number(metric.windowMinutes)
    if (!isFinite(minutes) || minutes <= 0) continue
    if (shortestWindow === null || minutes < shortestWindow || (minutes === shortestWindow && value > shortest)) {
      shortestWindow = minutes
      shortest = value
    }
  }
  return highest || shortest === null ? best : shortest
}

function longTermPercent(row) {
  if (!hasData(row) || !row.metrics) return null
  var longest = null
  var value = null
  for (var i = 0; i < row.metrics.length; i++) {
    var metric = row.metrics[i]
    var percent = Number(metric.percent)
    var minutes = Number(metric.windowMinutes)
    if (metric.percent === null || metric.percent === undefined || isNaN(percent)) continue
    if (!isFinite(minutes) || minutes <= 0) continue
    if (longest === null || minutes > longest || (minutes === longest && percent > value)) {
      longest = minutes
      value = percent
    }
  }
  return value === null ? primaryPercent(row, true) : value
}

function barValue(row, mode) {
  var used = primaryPercent(row)
  if (used === null) return percentText(null)
  var remaining = 100 - Math.round(used)
  if (mode === "remaining") return percentText(remaining)
  if (mode === "both") return percentText(used) + " / " + percentText(remaining)
  return percentText(used)
}

function percentModeText(used, mode) {
  var remaining = 100 - Math.round(used)
  if (mode === "remaining") return percentText(remaining)
  if (mode === "both") return percentText(used) + " / " + percentText(remaining)
  return percentText(used)
}

function barTooltip(mode, rows) {
  var lines = []
  for (var i = 0; i < (rows || []).length; i++) {
    if (!hasData(rows[i]) || !rows[i].metrics) continue
    var parts = []
    for (var j = 0; j < rows[i].metrics.length; j++) {
      var metric = rows[i].metrics[j]
      var value = Number(metric.percent)
      if (metric.percent === null || metric.percent === undefined || isNaN(value)) continue
      parts.push(metric.label + " " + percentModeText(value, mode))
    }
    if (parts.length > 0) lines.push(rows[i].name + ": " + parts.join(", "))
  }
  return lines.join("\n") || "AI usage"
}

function isWarning(row, threshold) {
  var value = primaryPercent(row, true)
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
  return ERROR_TEXT[row.error] || statusDetail(row)
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

function restoreCache(text) {
  var parsed = null
  try {
    parsed = JSON.parse(String(text || ""))
  } catch (error) {
    parsed = null
  }
  if (!parsed || !Array.isArray(parsed.rows)) return null
  var refreshedAt = typeof parsed.refreshedAt === "string" ? parsed.refreshedAt : ""
  var refreshedMs = Date.parse(refreshedAt)
  if (!refreshedAt || isNaN(refreshedMs)) return null
  // Reject future timestamps; a clock rollback must not suppress refreshes.
  if (refreshedMs > Date.now()) return null
  var rows = parsed.rows.filter(function(row) { return row && typeof row.provider === "string" })
  return { rows: rows, refreshedAt: refreshedAt, refreshedMs: refreshedMs }
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
  return value <= 75 ? "#4ade80" : value < 90 ? "#fb923c" : "#f87171"
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

// Share of the limit window already elapsed (0..1), or -1 when the window length is unknown.
function elapsedFraction(metric, nowMs) {
  var minutes = metric && Number(metric.windowMinutes)
  var target = minutes ? Date.parse(metric.resetsAt) : NaN
  if (isNaN(target)) return -1
  var now = (nowMs === undefined || nowMs === null) ? Date.now() : nowMs
  var left = (target - now) / (minutes * 60000)
  return left < 0 || left > 1 ? -1 : 1 - left
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

function providerColor(provider) {
  return USAGE_PROVIDER_COLORS[provider] || "#94a3b8"
}

function compactNumber(value) {
  var number = Number(value)
  if (!isFinite(number) || number <= 0) return "0"
  var units = [[1e9, "B"], [1e6, "M"], [1e3, "K"]]
  for (var i = 0; i < units.length; i++) {
    if (number >= units[i][0]) {
      var scaled = number / units[i][0]
      return (scaled >= 100 ? String(Math.round(scaled)) : String(Math.round(scaled * 10) / 10)) + units[i][1]
    }
  }
  return String(Math.round(number))
}

function dayProviderTokens(day, provider) {
  if (!day || !day.providers) return 0
  var value = Number(day.providers[provider])
  return isFinite(value) && value > 0 ? value : 0
}

function providerIds(window) {
  var out = []
  var list = window && window.providers ? window.providers : []
  for (var i = 0; i < list.length; i++) {
    if (list[i] && typeof list[i].id === "string") out.push(list[i].id)
  }
  return out
}

function localUsageProviders(enabled) {
  var list = providerList(enabled)
  var out = []
  for (var i = 0; i < USAGE_PROVIDERS.length; i++) {
    if (list.indexOf(USAGE_PROVIDERS[i]) >= 0) out.push(USAGE_PROVIDERS[i])
  }
  return out
}

function providerSummary(window, id) {
  var list = window && window.providers ? window.providers : []
  for (var i = 0; i < list.length; i++) {
    if (list[i] && list[i].id === id) return list[i]
  }
  return null
}

function dayMax(days, ids) {
  var max = 0
  for (var i = 0; i < days.length; i++) {
    var total = 0
    for (var j = 0; j < ids.length; j++) total += dayProviderTokens(days[i], ids[j])
    if (total > max) max = total
  }
  return max
}

function stackOffset(day, ids, index) {
  var total = 0
  for (var i = 0; i < index; i++) total += dayProviderTokens(day, ids[i])
  return total
}

function share(value, total) {
  return total > 0 ? Math.round(100 * Number(value) / total) + "%" : "0%"
}

function usageFooter(name) {
  if (name === "6m") return "Local logs \u00b7 last 6 months"
  if (name === "1y") return "Local logs \u00b7 last year"
  var days = USAGE_WINDOW_DAYS[name] || 7
  return days === 1 ? "Local logs \u00b7 today" : "Local logs \u00b7 last " + days + " days"
}

function usageWindowName(value) {
  return USAGE_WINDOWS.indexOf(value) >= 0 ? value : SETTING_DEFAULTS.usageWindow
}

function dayLabel(iso) {
  var parts = String(iso || "").split("-")
  return parts.length === 3 ? Number(parts[1]) + "/" + Number(parts[2]) : ""
}
