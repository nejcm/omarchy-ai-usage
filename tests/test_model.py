from __future__ import annotations

import json
import unittest

from support import model_source, requires_node, run_node
import providers as providers_pkg


class ModelTests(unittest.TestCase):
    @requires_node
    def test_model_reset_and_reorder(self):
        source = model_source()
        script = source + """
const assert = require("node:assert/strict");
const saved = {enabledProviders: ["claude", "codex"], providerOrder: ["cursor", "codex", "claude"],
  hiddenProviders: ["codex"], refreshIntervalSec: 180, displayMode: "both", warningThreshold: 50,
  colorWarnings: false, desktopNotifications: true,
  warningState: {"claude:Session": {period: "t", fired: true}}};
const reset = resetSettings(saved);
assert.deepEqual(reset.providerOrder, []);
assert.deepEqual(reset.enabledProviders, DEFAULT_ENABLED);
assert.deepEqual(reset.hiddenProviders, []);
assert.equal(reset.refreshIntervalSec, 300);
assert.equal(reset.displayMode, "used");
assert.equal(reset.warningThreshold, 80);
assert.equal(reset.colorWarnings, true);
assert.equal(reset.desktopNotifications, false);
assert.deepEqual(reset.warningState, saved.warningState);
assert.deepEqual(saved.providerOrder, ["cursor", "codex", "claude"]);
assert.deepEqual(resetSettings(null), SETTING_DEFAULTS);
assert.deepEqual(providerOrder(reset.providerOrder), PROVIDERS);
assert.deepEqual(enabledInOrder(providerOrder(reset.providerOrder), reset.enabledProviders), DEFAULT_ENABLED);
assert.deepEqual(selectedProviders(reset.enabledProviders, reset.hiddenProviders), DEFAULT_ENABLED);
const order = providerOrder(saved.providerOrder);
assert.deepEqual(order, ["cursor", "codex", "claude", "opencode", "grok", "antigravity", "zai"]);
assert.deepEqual(moveItem(order, "zai", 0), ["zai", "cursor", "codex", "claude", "opencode", "grok", "antigravity"]);
assert.deepEqual(moveItem(order, "claude", 0), ["claude", "cursor", "codex", "opencode", "grok", "antigravity", "zai"]);
assert.deepEqual(moveItem(order, "cursor", 2), ["codex", "claude", "cursor", "opencode", "grok", "antigravity", "zai"]);
assert.deepEqual(moveItem(order, "cursor", -1), order);
assert.deepEqual(moveItem(order, "grok", 99), ["cursor", "codex", "claude", "opencode", "antigravity", "zai", "grok"]);
assert.deepEqual(moveItem(order, "missing", 0), order);
assert.deepEqual(moveItem(saved.providerOrder, "claude", 0), ["claude", "cursor", "codex"]);
const seqOrder = {0: "cursor", 1: "codex", 2: "claude", length: 3};
assert.deepEqual(moveItem(seqOrder, "claude", 0), ["claude", "cursor", "codex"]);
console.log("OK");
"""
        run_node(self, script)

    @requires_node
    def test_model_restore_cache(self):
        source = model_source()
        script = source + """
const assert = require("node:assert/strict");
const rows = [{provider:"claude", status:"ok", metrics:[{percent:42}]},
  {provider:"codex", status:"ok", metrics:[{percent:8}]},
  {provider:"cursor", status:"ok", metrics:[{percent:2}]}];
const good = JSON.stringify({refreshedAt:"2020-01-01T00:00:00Z", rows});
const restored = restoreCache(good);
assert.deepEqual(restored.rows.map(row => row.provider), ["claude", "codex", "cursor"]);
assert.equal(restored.rows[0].metrics[0].percent, 42);
assert.equal(restored.refreshedAt, "2020-01-01T00:00:00Z");
assert.equal(restored.refreshedMs, Date.parse("2020-01-01T00:00:00Z"));
assert.deepEqual(restoreCache(JSON.stringify({refreshedAt:"2020-01-01T00:00:00Z", rows:[null, {}, rows[0]]})).rows, [rows[0]]);
assert.equal(restoreCache(""), null);
assert.equal(restoreCache("not json"), null);
assert.equal(restoreCache("null"), null);
assert.equal(restoreCache(JSON.stringify({rows})), null);
assert.equal(restoreCache(JSON.stringify({refreshedAt:"2026-10-12T10:00:00Z"})), null);
assert.equal(restoreCache(JSON.stringify({refreshedAt:"sometime", rows})), null);
assert.equal(restoreCache(JSON.stringify({refreshedAt:"2099-01-01T00:00:00Z", rows})), null);
assert.equal(restoreCache(JSON.stringify({refreshedAt:123, rows})), null);
assert.equal(restoreCache(JSON.stringify({refreshedAt:"2026-10-12T10:00:00Z", rows:"bad"})), null);
assert.equal(restoreCache(JSON.stringify({refreshedAt:"2026-10-12T10:00:00Z", rows:{}})), null);
"""
        run_node(self, script)

    @requires_node
    def test_settings_and_warning_periods(self):
        source = model_source()
        script = source + """
const assert = require("node:assert/strict");
assert.deepEqual(providerOrder(["cursor", "bad", "cursor"]), ["cursor", "claude", "codex", "opencode", "grok", "antigravity", "zai"]);
assert.deepEqual(providerOrder(null), PROVIDERS);
assert.deepEqual(selectedProviders(PROVIDERS, ["claude", "cursor"]), ["codex", "opencode", "grok", "antigravity", "zai"]);
assert.deepEqual(selectedProviders(PROVIDERS, PROVIDERS), []);
assert.deepEqual(selectedProviders(PROVIDERS, {}), PROVIDERS);
assert.deepEqual(selectedProviders(PROVIDERS, null), PROVIDERS);
assert.deepEqual(enabledInOrder(["cursor", "codex", "claude"], ["claude", "cursor"]), ["cursor", "claude"]);
assert.deepEqual(enabledInOrder(PROVIDERS, PROVIDERS), PROVIDERS);
for (const value of [[], {}, null]) assert.deepEqual(enabledInOrder(PROVIDERS, value), []);
const rows = PROVIDERS.map(provider => ({provider, status:"ok", metrics:[{percent:70.4}]}));
assert.deepEqual(orderedRows(rows, ["cursor", "claude"]).map(row => row.provider), ["cursor", "claude"]);
assert.equal(barValue(rows[0], "remaining"), "30%");
assert.equal(barValue(rows[0], "both"), "70% / 30%");
assert.equal(barValue({status:"unavailable"}, "remaining"), "–");
for (const minute of REFRESH_MINUTES) assert.equal(refreshSeconds(minute * 60), minute * 60);
for (const value of [0, -1, "bad", 240, Infinity, null]) assert.equal(refreshSeconds(value), 300);
assert.equal(warningThreshold("bad"), 80);
assert.equal(warningThreshold(0), 1);
assert.equal(warningThreshold(150), 100);
assert.equal(isWarning(rows[0], 70), true);
assert.equal(isWarning({status:"unavailable"}, 80), false);
assert.equal(isWarning({status:"ok", metrics:[{percent:10, windowMinutes:300}, {percent:100, windowMinutes:10080}]}, 90), true);
const row = {provider:"codex", name:"Codex", status:"ok", metrics:[
  {label:"Session", percent:85, resetsAt:"2030-01-01T00:00:00Z"},
  {label:"Weekly", percent:90, resetsAt:"2030-01-07T00:00:00Z"}]};
let result = warningEvents([row], {}, 80, false);
assert.equal(result.events.length, 0);
result = warningEvents([row], result.state, 80, true);
assert.equal(result.events.length, 2);
let state = JSON.parse(JSON.stringify(result.state));
assert.equal(warningEvents([row], state, 80, true).events.length, 0);
row.metrics[0].resetsAt = "2030-01-01T00:00:01.250Z";
assert.equal(warningEvents([row], state, 80, true).events.length, 0);
row.metrics[0].percent = 20;
state = warningEvents([row], state, 80, true).state;
row.metrics[0].percent = 85;
assert.equal(warningEvents([row], state, 80, true).events.length, 0);
row.metrics[0].resetsAt = "2030-01-01T05:00:00Z";
result = warningEvents([row], state, 80, true);
assert.equal(result.events.length, 1);
state = result.state;
row.status = "stale";
row.metrics[1].resetsAt = "2030-01-14T00:00:00Z";
assert.deepEqual(warningEvents([row], state, 80, true), {state, events:[]});
row.status = "ok";
row.metrics = [{label:"Total", percent:85, resetsAt:""}];
result = warningEvents([row], {}, 80, true);
assert.equal(result.events.length, 1);
assert.equal(warningEvents([row], result.state, 80, true).events.length, 0);
row.metrics[0].percent = 79;
state = warningEvents([row], result.state, 80, true).state;
row.metrics[0].percent = 85;
assert.equal(warningEvents([row], state, 80, true).events.length, 1);
row.metrics[0].percent = null;
assert.equal(warningEvents([row], {}, 80, true).events.length, 0);
assert.deepEqual(PROVIDERS, """ + json.dumps([module.ID for module in providers_pkg.REGISTRY]) + ");"
        run_node(self, script)

    @requires_node
    def test_model_usage_formatting_and_colors(self):
        source = model_source()
        script = source + """
const assert = require("node:assert/strict");
const row = {status:"ok", metrics:[{percent:18}, {percent:42}]};
assert.equal(barValue(row), "42%");
assert.equal(barValue({status:"unavailable", metrics:[]}), "–");
assert.equal(barValue({status:"ok", metrics:[]}), "–");
assert.equal(barValue({status:"ok", metrics:[{percent:null}, {}]}), "–");
assert.equal(barValue({status:"ok", metrics:[{percent:0}]}), "0%");
assert.equal(barValue({status:"ok", metrics:[
  {percent:5, windowMinutes:10080}, {percent:80, windowMinutes:300}]}), "80%");
assert.equal(barValue({status:"ok", metrics:[
  {percent:80, windowMinutes:0}, {percent:5, windowMinutes:300}]}), "5%");
assert.equal(barValue({status:"ok", metrics:[
  {percent:80, windowMinutes:-1}, {percent:5, windowMinutes:300}]}), "5%");
assert.equal(barValue({status:"ok", metrics:[
  {percent:80, windowMinutes:"bad"}, {percent:5, windowMinutes:300}]}), "5%");
assert.equal(barValue({status:"ok", metrics:[
  {percent:80}, {percent:5, windowMinutes:300}]}), "5%");
assert.equal(barValue({status:"ok", metrics:[
  {percent:10, windowMinutes:300}, {percent:90}]}), "10%");
assert.equal(barValue({status:"ok", metrics:[
  {percent:20, windowMinutes:300}, {percent:50, windowMinutes:300}]}), "50%");
assert.equal(barValue({status:"ok", metrics:[
  {percent:null, windowMinutes:1}, {percent:70, windowMinutes:300}]}), "70%");
for (const [value, color] of [[0,"#4ade80"], [75,"#4ade80"],
  [75.1,"#fb923c"], [90,"#fb923c"], [90.1,"#f87171"], [100,"#f87171"]]) {
  assert.equal(usageColor(value), color);
}
assert.equal(percentText(42.4), "42%");
assert.equal(percentText(42.5), "43%");
assert.equal(percentText(0), "0%");
assert.equal(percentText(null), "\u2013");
assert.equal(percentText(NaN), "\u2013");
"""
        run_node(self, script)

    @requires_node
    def test_model_status_hints_and_relative_time(self):
        source = model_source()
        script = source + """
const assert = require("node:assert/strict");
const now = Date.parse("2026-10-12T14:32:00Z");
assert.equal(updatedText("", now), "");
assert.equal(updatedText("bad", now), "");
assert.equal(updatedText("2026-10-12T14:31:45Z", now), "just now");
assert.equal(updatedText("2026-10-12T14:27:00Z", now), "5m ago");
assert.equal(updatedText("2026-10-12T12:32:00Z", now), "2h ago");
assert.equal(updatedText("2026-10-10T14:32:00Z", now), "2d ago");
assert.equal(statusText({status:"ok"}), "");
assert.equal(statusText({status:"not-signed-in"}), "not signed in");
const locked = {provider:"claude", status:"stale", error:"refresh-locked"};
assert.equal(statusText(locked), "Refreshing elsewhere");
assert.equal(statusDetail(locked), "stale (refresh-locked)");
assert.equal(statusHint(locked), "Retrying on the next update");
const expired = {provider:"claude", status:"expired", error:"http-401"};
assert.equal(statusText(expired), "Sign-in expired");
assert.equal(statusHint(expired), "Open claude to renew sign-in");
const limited = {provider:"codex", status:"rate-limited", error:"http-429"};
assert.equal(statusText(limited), "Rate limited");
assert.equal(statusHint(limited), "Raise the refresh interval");
const missing = {provider:"cursor", status:"not-signed-in"};
assert.equal(statusText(missing), "not signed in");
assert.equal(connectHint(missing), "Sign in with cursor-agent to connect");
assert.equal(connectHint({provider:"cursor", status:"ok"}), "");
assert.equal(anyNeedsSignIn([{status:"ok"}, missing]), true);
assert.equal(anyNeedsSignIn([{status:"ok"}]), false);
const persist = {provider:"claude", status:"error", error:"persist-write-failed"};
assert.equal(statusText(persist), "Could not save refreshed sign-in");
assert.equal(statusDetail(persist), "error (persist-write-failed)");
assert.equal(statusHint(persist), "");
assert.equal(statusHint({provider:"claude", status:"stale", error:"refresh-timeout"}),
  "Open claude to recover the sign-in");
assert.equal(statusText({status:"error", error:"some-new-code"}), "error (some-new-code)");
assert.equal(statusText({provider:"codex", status:"unavailable", error:"api-key-auth"}),
  "API key sign-in unsupported");
assert.equal(statusText({provider:"claude", status:"error", error:"persist-unreadable"}),
  "Credentials unreadable");
const good = {provider:"claude", name:"Claude Code", status:"ok",
  metrics:[{label:"Session", percent:42, resetsAt:""}], plan:"Pro", refreshedAt:"t1"};
const signedOut = mergeRows([good], [{provider:"claude", name:"Claude Code",
  status:"not-signed-in", error:"", metrics:[]}])[0];
assert.equal(signedOut.status, "stale");
assert.equal(signedOut.error, "not-signed-in");
assert.equal(statusText(signedOut), "Not signed in");
assert.equal(statusHint(signedOut), "Sign in with claude to connect");
assert.equal(connectHint(signedOut), "Sign in with claude to connect");
assert.equal(anyNeedsSignIn([signedOut]), true);
const expiredStale = mergeRows([good], [{provider:"claude", name:"Claude Code",
  status:"expired", error:"http-401", metrics:[]}])[0];
assert.equal(expiredStale.status, "stale");
assert.equal(statusHint(expiredStale), "Open claude to renew sign-in");
assert.equal(connectHint(expiredStale), "Open claude to renew sign-in");
assert.equal(anyNeedsSignIn([expiredStale]), true);
const weeklyRow = {provider:"claude", name:"Claude Code", status:"ok", metrics:[
  {label:"Session", percent:10, windowMinutes:300}, {label:"Weekly", percent:42, windowMinutes:10080}]};
const tipRows = [{provider:"claude", name:"Claude Code", status:"ok", metrics:[
  {label:"Session", percent:10, windowMinutes:300}, {label:"Weekly", percent:42, windowMinutes:10080}]},
  {provider:"cursor", name:"Cursor", status:"ok", metrics:[]}];
assert.equal(barTooltip("used", tipRows), "Claude Code: Session " + percentText(10) + ", Weekly " + percentText(42));
assert.equal(barTooltip("remaining", tipRows), "Claude Code: Session " + percentText(90) + ", Weekly " + percentText(58));
assert.equal(barTooltip("used", []), "AI usage");
assert.equal(TROUBLESHOOTING_URL, "https://github.com/nejcm/omarchy-ai-usage#troubleshooting");
"""
        run_node(self, script)

    @requires_node
    def test_provider_names_and_logos(self):
        source = model_source()
        script = source + """
const assert = require("node:assert/strict");
assert.deepEqual(PROVIDERS, ["claude", "codex", "opencode", "cursor", "grok", "antigravity", "zai"]);
assert.deepEqual(PROVIDERS.map(id => PROVIDER_INFO[id].name),
  ["Claude Code", "Codex", "OpenCode", "Cursor", "Grok", "Antigravity", "Z.ai"]);
assert.deepEqual(PROVIDERS.map(id => logo(id, false)),
  ["claude.svg", "chatgpt.svg", "opencode.svg", "cursor.svg", "grok.svg", "antigravity.svg", "z.ai.svg"]);
assert.deepEqual(PROVIDERS.map(id => logo(id, true)),
  ["claude.white.svg", "chatgpt.white.svg", "opencode.white.svg", "cursor.white.svg", "grok.white.svg", "antigravity.white.svg", "z.ai.white.svg"]);
assert.deepEqual(PROVIDERS.map(panelLogo),
  ["claude.svg", "chatgpt.white.svg", "opencode.white.svg", "cursor.white.svg", "grok.white.svg", "antigravity.svg", "z.ai.white.svg"]);
assert.equal(logo("unknown", true), "");
assert.equal(panelLogo("unknown"), "");
"""
        run_node(self, script)

    @requires_node
    def test_model_merge_keeps_cache_across_failures(self):
        source = model_source()
        script = source + """
var rows = [];
rows = mergeRows(rows, [{provider:"x",name:"X",abbrev:"X",status:"ok",plan:"P",
  metrics:[{label:"S",percent:42,resetsAt:""}],resetAt:"",refreshedAt:"t1"}]);
rows = mergeRows(rows, [{provider:"x",name:"X",abbrev:"X",status:"rate-limited",error:"http-429",
  metrics:[],resetAt:"",refreshedAt:"t2"}]);
rows = mergeRows(rows, [{provider:"x",name:"X",abbrev:"X",status:"rate-limited",error:"http-429",
  metrics:[],resetAt:"",refreshedAt:"t3"}]);
console.log(JSON.stringify({rows:rows, marked:markStale(rows)}));
"""
        payload = json.loads(run_node(self, script))
        for rows in (payload["rows"], payload["marked"]):
            self.assertEqual(rows[0]["status"], "stale")
            self.assertEqual(rows[0]["metrics"][0]["percent"], 42)
            self.assertEqual(rows[0]["refreshedAt"], "t1")


if __name__ == "__main__":
    unittest.main()
