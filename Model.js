.pragma library

// Pure formatting and merge helpers shared by the bar widget and the panel.

var LOGOS = { claude: "claude", codex: "chatgpt", opencode: "opencode", cursor: "cursor" }

var STATUS = {
  "stale": "stale",
  "not-signed-in": "not signed in",
  "expired": "sign-in expired",
  "unavailable": "unavailable",
  "rate-limited": "rate limited",
  "error": "error"
}

function logo(provider, white) {
  var name = LOGOS[provider]
  return name ? name + (white ? ".white" : "") + ".svg" : ""
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

function barValue(row) {
  return percentText(primaryPercent(row))
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
