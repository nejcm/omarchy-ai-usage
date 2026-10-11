.pragma library

// Pure formatting helpers shared by the bar widget and the panel.

var ABBREV = { claude: "C", codex: "X", opencode: "O", cursor: "U" }

var STATUS = {
  "not-signed-in": "not signed in",
  "expired": "sign-in expired",
  "unavailable": "unavailable",
  "rate-limited": "rate limited",
  "error": "error"
}

function abbrev(provider) {
  return ABBREV[provider] || String(provider || "?").slice(0, 1).toUpperCase()
}

function isOk(row) {
  return !!row && row.status === "ok"
}

function primaryPercent(row) {
  if (!isOk(row) || !row.metrics || row.metrics.length === 0) return null
  var best = null
  for (var i = 0; i < row.metrics.length; i++) {
    var value = Number(row.metrics[i].percent)
    if (isNaN(value)) continue
    if (best === null || value > best) best = value
  }
  return best
}

function tokenFor(row) {
  var letter = abbrev(row.provider)
  var value = primaryPercent(row)
  return value === null ? letter + " \u2013" : letter + " " + Math.round(value)
}

function barText(rows) {
  if (!rows || rows.length === 0) return "AI"
  var parts = []
  for (var i = 0; i < rows.length; i++) parts.push(tokenFor(rows[i]))
  return parts.join(" \u00b7 ")
}

function planText(row) {
  return row && row.plan ? row.plan : ""
}

function statusText(row) {
  if (!row || row.status === "ok") return ""
  var label = STATUS[row.status] || row.status
  return row.error ? label + " (" + row.error + ")" : label
}

function percentText(value) {
  return value === null || value === undefined || isNaN(value) ? "\u2013" : Math.round(value) + "%"
}

function resetText(iso) {
  if (!iso) return ""
  var target = Date.parse(iso)
  if (isNaN(target)) return ""
  var minutes = Math.floor((target - Date.now()) / 60000)
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
