from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from support import ROOT


class QmlTests(unittest.TestCase):
    @unittest.skipUnless(Path("/usr/lib/qt6/bin/qmltestrunner").exists(), "Qt 6 QML test runner not installed")
    def test_qml_provider_settings_after_restart(self):
        result = subprocess.run(
            ["/usr/lib/qt6/bin/qmltestrunner", "-input", str(ROOT / "tests/tst_provider_settings.qml"), "-o", "-,txt"],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                 "QT_QUICK_BACKEND": "software", "QT_LOGGING_TO_CONSOLE": "1"},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(Path("/usr/lib/qt6/bin/qmltestrunner").exists(), "Qt 6 QML test runner not installed")
    def test_qml_settings_reset_flow(self):
        result = subprocess.run(
            ["/usr/lib/qt6/bin/qmltestrunner", "-import", str(ROOT / "tests/qml-stubs"),
             "-input", str(ROOT / "tests/tst_settings_reset.qml"), "-o", "-,txt"],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                 "QT_QUICK_BACKEND": "software", "QT_LOGGING_TO_CONSOLE": "1"},
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(Path("/usr/lib/qt6/bin/qmltestrunner").exists(), "Qt 6 QML test runner not installed")
    def test_qml_local_usage_toggle(self):
        result = subprocess.run(
            ["/usr/lib/qt6/bin/qmltestrunner", "-import", str(ROOT / "tests/qml-stubs"),
             "-input", str(ROOT / "tests/tst_local_usage.qml"), "-o", "-,txt"],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
                 "QT_QUICK_BACKEND": "software", "QT_LOGGING_TO_CONSOLE": "1"},
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_widget_local_usage_process(self):
        source = (ROOT / "Model.js").read_text().replace(".pragma library", "")
        script = source + "\nconst qml = " + json.dumps((ROOT / "BarWidget.qml").read_text()) + \
            ";\nconst usageQml = " + json.dumps((ROOT / "LocalUsage.qml").read_text()) + ";" + """
const assert = require("node:assert/strict");
const Model = {orderedRows: orderedRows};
const root = {localUsage:false, enabledProviders:["claude", "codex"], script:"/plugin path/usage.py",
  usage:null, usagePending:false, usageSelectionKey:"", refreshing:false, refreshPending:false, rows:[],
  lastAttemptMs:0, loadedOnce:false, cacheChecked:false, selectionKey:"claude,codex",
  Qt:{callLater(fn) { fn(); }}, refreshCalls:0, staleCalls:0};
root.refresh = function() { root.refreshCalls += 1; };
root.refreshIfStale = function() { root.staleCalls += 1; };
const localUsageProcess = {running:false, command:null};
function method(name) {
  const start = qml.indexOf("  function " + name + "(");
  const end = qml.indexOf("\\n  }", start) + 4;
  assert(start >= 0 && end > start);
  return new Function("root", "localUsageProcess", "Model",
    "with (root) { return (" + qml.slice(start, end) + ") }")(root, localUsageProcess, Model);
}
const refreshUsage = method("refreshUsage");
refreshUsage();
assert.equal(localUsageProcess.running, false);
assert.equal(localUsageProcess.command, null);
root.localUsage = true;
refreshUsage();
assert.deepEqual(localUsageProcess.command,
  ["python3", "/plugin path/usage.py", "--usage", "--provider", "claude", "--provider", "codex"]);
assert.equal(localUsageProcess.running, true);
assert.equal(root.usageSelectionKey, "claude,codex");
refreshUsage();
assert.equal(root.usagePending, true);
localUsageProcess.running = false;
root.usagePending = false;
root.enabledProviders = [];
refreshUsage();
assert.equal(localUsageProcess.running, false);
root.enabledProviders = ["claude", "codex"];
const applyUsageOutput = method("applyUsageOutput");
applyUsageOutput(JSON.stringify({usage:{scanning:false, windows:{"7d":{tokens:5}}}}));
assert.deepEqual(root.usage, {scanning:false, windows:{"7d":{tokens:5}}});
applyUsageOutput("bad json");
assert.deepEqual(root.usage, {scanning:false, windows:{"7d":{tokens:5}}});
root.selectionKey = "claude";
applyUsageOutput(JSON.stringify({usage:{scanning:false, windows:{"7d":{tokens:99}}}}));
assert.deepEqual(root.usage, {scanning:false, windows:{"7d":{tokens:5}}});
root.usageSelectionKey = "claude";
applyUsageOutput(JSON.stringify({usage:{scanning:false, windows:{"7d":{tokens:7}}}}));
assert.deepEqual(root.usage, {scanning:false, windows:{"7d":{tokens:7}}});
root.refreshUsage = function() { root.refreshUsageCalls = (root.refreshUsageCalls || 0) + 1; };
function handler(name) {
  const start = qml.indexOf("  " + name + ": {");
  assert(start >= 0);
  const open = qml.indexOf("{", start) + 1;
  const end = qml.indexOf("\\n  }", open);
  assert(end > open);
  return new Function("root", "localUsageProcess", "Model",
    "with (root) { return (function() {" + qml.slice(open, end) + "}) }")(root, localUsageProcess, Model);
}
const localUsageChanged = handler("onLocalUsageChanged");
root.localUsage = true;
localUsageChanged();
assert.equal(root.refreshUsageCalls, 1);
localUsageProcess.running = true;
root.usage = {scanning:false};
root.localUsage = false;
localUsageChanged();
assert.equal(localUsageProcess.running, false);
assert.equal(root.usage, null);
const selectionChanged = handler("onSelectionKeyChanged");
root.localUsage = true;
root.lastAttemptMs = 1;
root.usage = {scanning:false};
root.selectionKey = "codex";
localUsageProcess.running = true;
selectionChanged();
assert.equal(root.usage, null);
assert.equal(localUsageProcess.running, false);
assert.equal(root.usagePending, true);
assert.equal(root.refreshCalls, 1);
root.usage = {scanning:false};
root.usagePending = false;
localUsageProcess.running = false;
const starts = root.refreshUsageCalls || 0;
selectionChanged();
assert.equal(root.usage, null);
assert.equal(root.usagePending, false);
assert.equal(root.refreshUsageCalls, starts + 1);
function quotaExited() {
  const marker = qml.indexOf("  onExited: function(");
  assert(marker >= 0);
  const start = marker + "  onExited: ".length;
  const end = qml.indexOf("\\n    }", start) + 6;
  assert(end > start);
  return new Function("root", "localUsageProcess", "Model",
    "with (root) { return (" + qml.slice(start, end) + ") }")(root, localUsageProcess, Model);
}
quotaExited()(0, 0);
assert.equal(root.refreshUsageCalls, starts + 2);
const saved = [];
const usageRoot = {hostWidget: {saveSetting(name, value) { saved.push([name, value]); }}};
const selectorMarker = usageQml.indexOf('{ value: "today"');
assert(selectorMarker >= 0);
const marker = usageQml.indexOf("onChanged: function (value) {", selectorMarker);
assert(marker >= 0);
const endMarker = "\\n    }";
const end = usageQml.indexOf(endMarker, marker) + endMarker.length;
assert(end > marker);
new Function("root", "with (root) { return (" + usageQml.slice(marker + "onChanged: ".length, end) + ") }")(usageRoot)("30d");
assert.deepEqual(saved, [["usageWindow", "30d"]]);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_widget_collection_selection_and_late_output(self):
        source = (ROOT / "Model.js").read_text().replace(".pragma library", "")
        script = source + "\nconst qml = " + json.dumps((ROOT / "BarWidget.qml").read_text()) + ";" + """
const assert = require("node:assert/strict");
const root = {enabledProviders:[], loadedOnce:false, refreshPending:false,
  refreshing:false, lastAttemptMs:0, cachedAtMs:0, cacheChecked:false, refreshMs:300000, rows:[], refreshedAt:"",
  script:"/plugin path/usage.py",
  get displayRows() { return Model.orderedRows(this.rows, this.enabledProviders); },
  Qt:{callLater(fn) { fn(); }},
  cacheFile:{setText(text) { root.cachedText = text; }},
  checkWarnings(rows) { this.warningRows = rows; }};
root.refreshUsage = function() { root.usageCalls = (root.usageCalls || 0) + 1; };
const process = {running:false};
const localUsageProcess = {running:false};
const Model = {orderedRows, mergeRows, markStale, restoreCache};
function method(name) {
  const start = qml.indexOf("  function " + name + "(");
  const end = qml.indexOf("\\n  }", start) + 4;
  assert(start >= 0 && end > start);
  return new Function("root", "usageProcess", "Model",
    "with (root) { return (" + qml.slice(start, end) + ") }")(root, process, Model);
}
const refresh = method("refresh");
refresh();
assert.equal(process.running, false);
assert.equal(root.loadedOnce, true);
root.enabledProviders = ["cursor", "codex"];
refresh();
assert.deepEqual(process.command, ["python3", "/plugin path/usage.py", "--provider", "cursor", "--provider", "codex"]);
assert.equal(process.running, true);
assert(root.lastAttemptMs > 0);
root.enabledProviders = ["codex"];
refresh();
assert.equal(root.refreshPending, true);
method("applyOutput")(JSON.stringify({providers:[
  {provider:"cursor", status:"ok", metrics:[]},
  {provider:"codex", status:"ok", metrics:[{percent:90}]}]}));
assert.deepEqual(root.rows.map(row => row.provider), ["codex"]);
assert.deepEqual(root.warningRows.map(row => row.provider), ["codex"]);
process.running = false;
refresh();
assert.equal(root.refreshPending, false);
assert.deepEqual(process.command, ["python3", "/plugin path/usage.py", "--provider", "codex"]);
method("applyOutput")("invalid json");
assert.equal(root.rows[0].status, "stale");
assert.equal(root.cacheChecked, true);
const cached = JSON.parse(root.cachedText);
assert.deepEqual(cached.rows.map(row => row.provider), ["codex"]);
assert.equal(cached.refreshedAt, "");
root.refreshCalls = 0;
root.refresh = function() { root.refreshCalls += 1; };
const stale = method("refreshIfStale");
root.refreshIfStale = stale;
root.lastAttemptMs = 0;
root.cachedAtMs = Date.now();
stale();
assert.equal(root.refreshCalls, 0);
root.cachedAtMs = Date.now() - 600000;
stale();
assert.equal(root.refreshCalls, 1);
root.lastAttemptMs = Date.now();
root.cachedAtMs = 0;
stale();
assert.equal(root.refreshCalls, 1);
const restore = method("restoreCache");
root.cachedAtMs = 0;
root.refreshedAt = "";
root.cacheChecked = false;
restore(JSON.stringify({refreshedAt:"2020-01-01T00:00:00Z",
  rows:[{provider:"codex", status:"ok", metrics:[]}]}));
assert.equal(root.cacheChecked, true);
assert.equal(root.rows[0].status, "stale");
assert.equal(root.cachedAtMs, 0);
root.rows = [];
root.cacheChecked = false;
restore("bad json");
assert.equal(root.cacheChecked, true);
assert.deepEqual(root.rows, []);
assert.equal(root.cachedAtMs, 0);
restore(JSON.stringify({refreshedAt:"2020-01-01T00:00:00Z",
  rows:[{provider:"codex", status:"ok", metrics:[]}]}));
assert.deepEqual(root.rows.map(row => row.provider), ["codex"]);
assert.equal(root.refreshedAt, "2020-01-01T00:00:00Z");
assert.equal(root.cachedAtMs, Date.parse("2020-01-01T00:00:00Z"));
function handler(name) {
  const start = qml.indexOf("  " + name + ": {");
  const end = qml.indexOf("\\n  }", start) + 4;
  assert(start >= 0 && end > start);
  return new Function("root", "usageProcess", "localUsageProcess", "Model",
    "with (root) { return " + qml.slice(start, end).replace(name + ": {", "(function() {") + ") }")(root, process, localUsageProcess, Model);
}
root.rows = [];
root.enabledProviders = ["codex"];
root.lastAttemptMs = 0;
root.loadedOnce = false;
restore(JSON.stringify({refreshedAt:"2020-01-01T00:00:00Z",
  rows:[{provider:"claude", status:"ok", metrics:[]}]}));
assert.deepEqual(root.rows.map(row => row.provider), ["claude"]);
root.enabledProviders = ["codex", "claude"];
handler("onSelectionKeyChanged")();
assert.deepEqual(root.rows.map(row => row.provider), ["claude"]);
root.refreshCalls = 0;
root.lastAttemptMs = 0;
root.loadedOnce = false;
root.rows = [{provider:"codex", status:"ok", metrics:[]}];
root.enabledProviders = ["codex", "cursor"];
root.cachedAtMs = Date.now();
stale();
assert.equal(root.refreshCalls, 1);
root.refreshCalls = 0;
root.enabledProviders = ["codex"];
stale();
assert.equal(root.refreshCalls, 0);
root.rows = [{provider:"codex", status:"ok", metrics:[]}, {provider:"claude", status:"ok", metrics:[]}];
root.enabledProviders = ["codex", "claude"];
root.cacheChecked = true;
handler("onSelectionKeyChanged")();
assert.equal(root.refreshCalls, 0);
root.enabledProviders = ["claude"];
handler("onSelectionKeyChanged")();
assert.equal(root.refreshCalls, 0);
root.refreshCalls = 0;
root.rows = [];
root.enabledProviders = ["codex"];
restore(JSON.stringify({refreshedAt:new Date().toISOString(),
  rows:[{provider:"codex", status:"ok", metrics:[]}]}));
assert(root.cachedAtMs > 0);
root.enabledProviders = ["codex", "cursor"];
handler("onSelectionKeyChanged")();
assert.equal(root.refreshCalls, 1);
"""
        subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_defaults_and_settings_persistence(self):
        source = (ROOT / "Model.js").read_text().replace(".pragma library", "")
        qml = (ROOT / "BarWidget.qml").read_text()
        extracted = {}
        for name in ("writeSettings", "saveSetting", "resetSettings", "toggleProviderList"):
            start = qml.index("  function " + name + "(")
            end = qml.index("\n  }", start) + 4
            assert qml[start:end].endswith("\n  }")
            extracted[name] = qml[start:end]
        methods = "\n".join(extracted[name] for name in ("writeSettings", "saveSetting", "resetSettings", "toggleProviderList"))
        script = source + "\nconst settingsQml = " + json.dumps((ROOT / "Settings.qml").read_text()) + ";" + """
const assert = require("node:assert/strict");
const MODEL = "io.github.nejcm.ai-usage";
const Model = { DEFAULT_ENABLED: DEFAULT_ENABLED, SETTING_DEFAULTS: SETTING_DEFAULTS,
  resetSettings: resetSettings, enabledInOrder: enabledInOrder,
  selectedProviders: selectedProviders, providerOrder: providerOrder, providerList: providerList };
function makeHost() {
  let disk = { id: MODEL };
  const layout = { left: [], center: [], right: [{ id: MODEL }] };
  let derived = { layout: JSON.parse(JSON.stringify(layout)) };
  let exposed = { layout: JSON.parse(JSON.stringify(layout)) };
  const instances = [];
  return {
    register: function(root) { instances.push(root); },
    shell: {
      get barConfig() { return exposed; },
      updateEntryInline: function(id, settings) {
        exposed = derived;
        const entry = Object.assign({ id: id }, JSON.parse(JSON.stringify(settings)));
        layout.right[0] = entry;
        disk = JSON.parse(JSON.stringify(entry));
        for (const root of instances) root.settings = JSON.parse(JSON.stringify(entry));
        derived = { layout: JSON.parse(JSON.stringify(layout)) };
      }
    },
    disk: function() { return JSON.parse(JSON.stringify(disk)); },
    reload: function() {
      layout.right[0] = JSON.parse(JSON.stringify(disk));
      derived = { layout: JSON.parse(JSON.stringify(layout)) };
      exposed = { layout: JSON.parse(JSON.stringify(layout)) };
    }
  };
}
function makeWidget(host, injected) {
  const root = { moduleName: MODEL, settings: injected, bar: { shell: host.shell } };
  function setting(name, fallback) {
    const value = root.settings ? root.settings[name] : undefined;
    return value === undefined || value === null ? fallback : value;
  }
""" + methods + """
  root.setting = setting;
  root.saveSetting = saveSetting;
  root.resetSettings = resetSettings;
  root.toggleProviderList = toggleProviderList;
  host.register(root);
  return { root: root, setting: setting, saveSetting: saveSetting, resetSettings: resetSettings, toggleProviderList: toggleProviderList };
}
function clickToggle(widget, name, id) {
  const line = settingsQml.split("\\n").find(line => line.includes('toggleProviderList("' + name + '"'));
  assert(line);
  new Function("root", "provider", "Model", line.trim().replace(/^onClicked:\\s*/, ""))(
    {hostWidget: widget.root}, {modelData: id}, Model);
}
const host = makeHost();
const a = makeWidget(host, host.disk());
const b = makeWidget(host, host.disk());

assert.deepEqual(a.setting("enabledProviders", DEFAULT_ENABLED), ["claude", "codex"]);
clickToggle(a, "enabledProviders", "cursor");
assert.deepEqual(host.disk().enabledProviders, ["claude", "codex", "cursor"]);
assert.deepEqual(DEFAULT_ENABLED, ["claude", "codex"]);
assert.equal(host.shell.barConfig.layout.right[0].enabledProviders, undefined);
clickToggle(b, "hiddenProviders", "cursor");
assert.deepEqual(host.disk().hiddenProviders, ["cursor"]);
clickToggle(b, "hiddenProviders", "cursor");
assert.deepEqual(host.disk().hiddenProviders, []);
clickToggle(a, "enabledProviders", "cursor");
assert.deepEqual(host.disk().enabledProviders, ["claude", "codex"]);
clickToggle(a, "enabledProviders", "cursor");

b.saveSetting("warningState", { "cursor:Cursor models": { period: "t", fired: true } });
assert.deepEqual(host.disk().enabledProviders, ["claude", "codex", "cursor"]);
assert.equal(host.disk().warningState["cursor:Cursor models"].fired, true);

a.saveSetting("providerOrder", ["cursor", "codex", "claude", "opencode", "grok", "antigravity", "zai"]);
a.saveSetting("refreshIntervalSec", 180);

host.reload();
const restarted = makeWidget(host, host.disk());
assert.deepEqual(restarted.setting("enabledProviders", DEFAULT_ENABLED), ["claude", "codex", "cursor"]);
assert.deepEqual(Model.enabledInOrder(restarted.setting("providerOrder", []), restarted.setting("enabledProviders", [])), ["cursor", "codex", "claude"]);
assert.equal(restarted.setting("refreshIntervalSec", 300), 180);
assert.equal(restarted.setting("warningState", {})["cursor:Cursor models"].fired, true);
restarted.root.settings.enabledProviders = {0: "claude", 1: "codex", length: 2};
clickToggle(restarted, "enabledProviders", "cursor");
assert.deepEqual(host.disk().enabledProviders, ["claude", "codex", "cursor"]);

restarted.saveSetting("displayMode", "both");
restarted.saveSetting("warningThreshold", 60);
restarted.saveSetting("colorWarnings", false);
assert.equal(host.disk().displayMode, "both");
assert.equal(host.disk().colorWarnings, false);

restarted.resetSettings();
const resetDisk = host.disk();
assert.deepEqual(resetDisk.providerOrder, SETTING_DEFAULTS.providerOrder);
assert.deepEqual(resetDisk.enabledProviders, SETTING_DEFAULTS.enabledProviders);
assert.deepEqual(resetDisk.hiddenProviders, SETTING_DEFAULTS.hiddenProviders);
assert.equal(resetDisk.refreshIntervalSec, SETTING_DEFAULTS.refreshIntervalSec);
assert.equal(resetDisk.displayMode, SETTING_DEFAULTS.displayMode);
assert.equal(resetDisk.warningThreshold, SETTING_DEFAULTS.warningThreshold);
assert.equal(resetDisk.colorWarnings, SETTING_DEFAULTS.colorWarnings);
assert.equal(resetDisk.desktopNotifications, SETTING_DEFAULTS.desktopNotifications);
assert.equal(resetDisk.warningState["cursor:Cursor models"].fired, true);

host.reload();
const resetWidget = makeWidget(host, host.disk());
assert.deepEqual(resetWidget.setting("enabledProviders", SETTING_DEFAULTS.enabledProviders), DEFAULT_ENABLED);
assert.deepEqual(Model.providerOrder(resetWidget.setting("providerOrder", SETTING_DEFAULTS.providerOrder)), PROVIDERS);
assert.equal(resetWidget.setting("refreshIntervalSec", SETTING_DEFAULTS.refreshIntervalSec), 300);
assert.equal(resetWidget.setting("displayMode", SETTING_DEFAULTS.displayMode), "used");
assert.equal(resetWidget.setting("warningThreshold", SETTING_DEFAULTS.warningThreshold), 80);
assert.equal(resetWidget.setting("colorWarnings", SETTING_DEFAULTS.colorWarnings), true);
assert.equal(resetWidget.setting("desktopNotifications", SETTING_DEFAULTS.desktopNotifications), false);
console.log("OK");
"""
        subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
