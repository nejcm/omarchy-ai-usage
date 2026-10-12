.pragma library

// Pure formatting, provider-selection, and merge helpers for the widget and panel.

var PROVIDER_INFO = {
  claude: { name: "Claude Code", logo: "claude", mono: false },
  codex: { name: "Codex", logo: "chatgpt", mono: true },
  opencode: { name: "OpenCode", logo: "opencode", mono: false },
  cursor: { name: "Cursor", logo: "cursor", mono: true },
  grok: { name: "Grok", logo: "grok", mono: true },
  antigravity: { name: "Antigravity", logo: "antigravity", mono: false },
  zai: { name: "Z.ai", logo: "z.ai", mono: true }
}
var PROVIDERS = Object.keys(PROVIDER_INFO)
var REFRESH_MINUTES = [1, 2, 3, 5, 10, 15, 30, 60]
var DEFAULT_ENABLED = ["claude", "codex"]

function enabledInOrder(order, enabled) {
  var list = Array.isArray(enabled) ? enabled : []
  return order.filter(function(id) { return list.indexOf(id) >= 0 })
}

function providerOrder(saved) {
  var order = []
  var requested = Array.isArray(saved) ? saved : []
  for (var i = 0; i < requested.length; i++) {
    if (PROVIDERS.indexOf(requested[i]) >= 0 && order.indexOf(requested[i]) < 0) order.push(requested[i])
  }
  for (var j = 0; j < PROVIDERS.length; j++) {
    if (order.indexOf(PROVIDERS[j]) < 0) order.push(PROVIDERS[j])
  }
  return order
}

function selectedProviders(order, hidden) {
  return order.filter(function(id) {
    return !Array.isArray(hidden) || hidden.indexOf(id) < 0
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
  var label = STATUS[row.status] || row.status
  return row.error ? label + " (" + row.error + ")" : label
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

function clockText(iso) {
  if (!iso) return ""
  var date = new Date(iso)
  if (isNaN(date.getTime())) return ""
  var hours = date.getHours()
  var minutes = date.getMinutes()
  return (hours < 10 ? "0" : "") + hours + ":" + (minutes < 10 ? "0" : "") + minutes
}
