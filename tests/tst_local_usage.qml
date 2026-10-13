import QtQuick
import QtTest
import "../Model.js" as Model

Item {
  id: harness
  width: 400
  height: 800

  QtObject {
    id: host

    property var providerOrder: []
    property var rows: []
    property var enabledProviders: []
    property int refreshMs: 300000
    property string displayMode: "used"
    property int warningThreshold: 80
    property bool colorWarnings: true
    property bool desktopNotifications: false
    property bool localUsage: true
    property var saved: []

    function setting(name, fallback) {
      return name === "localUsage" ? localUsage : fallback
    }

    function saveSetting(name, value) {
      saved.push([name, value])
      if (name === "localUsage") localUsage = value
    }

    function toggleProviderList() {}
    function moveProvider() {}
    function moveProviderToTop() {}
    function resetSettings() {}
  }

  QtObject {
    id: panelHost

    property var settings: ({})
    property bool localUsage: true
    property var usage: ({ scanning: false, windows: {} })
    property var displayRows: []
    property var rows: []
    property var providerOrder: []
    property var enabledProviders: ["claude"]
    property string refreshedAt: ""
    property bool refreshing: false
    property bool colorWarnings: true
    property int warningThreshold: 80
    property string displayMode: "used"
    property int refreshMs: 300000
    property bool desktopNotifications: false
    property var saved: []

    function setting(name, fallback) {
      var value = settings ? settings[name] : undefined
      return value === undefined || value === null ? fallback : value
    }

    function saveSetting(name, value) {
      saved.push([name, value])
      var next = Object.assign({}, settings)
      next[name] = value
      settings = next
    }

    function refresh() {}
    function refreshIfStale() {}
    function toggleProviderList() {}
    function moveProvider() {}
    function moveProviderToTop() {}
    function resetSettings() {}
  }

  Loader {
    id: loader
    anchors.fill: parent
  }

  Loader {
    id: widgetLoader
    anchors.fill: parent
  }

  Loader {
    id: panelLoader
    anchors.fill: parent
  }

  function find(rootItem, predicate) {
    if (!rootItem) return null
    if (predicate(rootItem)) return rootItem
    var data = rootItem.data || []
    for (var i = 0; i < data.length; i++) {
      var found = find(data[i], predicate)
      if (found) return found
    }
    return null
  }

  TestCase {
    name: "LocalUsage"
    when: windowShown

    function settings() {
      return loader.item
    }

    function usageToggle() {
      return harness.find(settings(), function(item) { return item.label === "Local token usage" })
    }

    function initTestCase() {
      compare(Model.SETTING_DEFAULTS.localUsage, true)
      compare(Model.SETTING_DEFAULTS.usageWindow, "7d")
      compare(Model.USAGE_WINDOWS, ["today", "7d", "30d"])
      compare(Model.usageWindowName("today"), "today")
      compare(Model.usageWindowName("30d"), "30d")
      compare(Model.usageWindowName("bogus"), "7d")
      compare(Model.usageWindowName(undefined), "7d")
      compare(Model.usageFooter("today"), "Local logs \u00b7 today")
      compare(Model.usageFooter("7d"), "Local logs \u00b7 last 7 days")
      compare(Model.usageFooter("30d"), "Local logs \u00b7 last 30 days")
      compare(Model.compactNumber(0), "0")
      compare(Model.compactNumber(999), "999")
      compare(Model.compactNumber(1200), "1.2K")
      compare(Model.compactNumber(37000000), "37M")
      compare(Model.share(25, 100), "25%")
      compare(Model.share(0, 0), "0%")
    }

    function init() {
      host.localUsage = true
      host.saved = []
      loader.setSource(Qt.resolvedUrl("../Settings.qml"), { hostWidget: host })
      verify(settings() !== null)
      verify(usageToggle() !== null)
    }

    function test_toggle_defaults_on() {
      compare(usageToggle().checked, true)
    }

    function test_toggle_off_saves_false() {
      usageToggle().clicked()
      compare(host.saved.length, 1)
      compare(host.saved[0][0], "localUsage")
      compare(host.saved[0][1], false)
      compare(usageToggle().checked, false)
    }

    function test_toggle_back_on_saves_true() {
      usageToggle().clicked()
      usageToggle().clicked()
      compare(host.saved.length, 2)
      compare(host.saved[1][0], "localUsage")
      compare(host.saved[1][1], true)
      compare(usageToggle().checked, true)
    }
  }

  TestCase {
    name: "UsageProcess"
    when: windowShown

    function widget() {
      return widgetLoader.item
    }

    function usageProcess() {
      return harness.find(widget(), function(item) {
        return item.command !== undefined && item.command.indexOf("--usage") >= 0
      })
    }

    function quotaProcess() {
      return harness.find(widget(), function(item) {
        return item.command !== undefined && item.command.indexOf("--usage") < 0
      })
    }

    function initTestCase() {
      widgetLoader.setSource(Qt.resolvedUrl("../BarWidget.qml"),
        { settings: { enabledProviders: ["claude", "codex"] } })
      verify(widget() !== null)
      verify(usageProcess() !== null)
    }

    function cleanup() {
      usageProcess().running = false
    }

    function test_default_on_starts_the_usage_scan() {
      var process = usageProcess()
      widget().settings = { localUsage: true, enabledProviders: ["claude", "codex"] }
      process.starts = 0
      widget().refreshUsage()
      compare(process.running, true)
      compare(process.starts, 1)
      compare(process.command, ["python3", widget().script, "--usage",
                                "--provider", "claude", "--provider", "codex"])
    }

    function test_toggle_off_runs_no_process() {
      var process = usageProcess()
      process.running = false
      process.starts = 0
      widget().settings = { localUsage: false, enabledProviders: ["claude", "codex"] }
      widget().refreshUsage()
      compare(widget().localUsage, false)
      compare(process.running, false)
      compare(process.starts, 0)
    }

    function test_toggle_off_cancels_a_running_scan() {
      var process = usageProcess()
      widget().settings = { localUsage: true, enabledProviders: ["claude"] }
      widget().refreshUsage()
      compare(process.running, true)
      widget().settings = { localUsage: false, enabledProviders: ["claude"] }
      compare(widget().localUsage, false)
      compare(process.running, false)
    }

    function test_stream_output_updates_usage() {
      var process = usageProcess()
      widget().settings = { localUsage: true, enabledProviders: ["claude"] }
      widget().usage = null
      widget().refreshUsage()
      process.emitStream(JSON.stringify({ usage: { scanning: false, windows: { "7d": { tokens: 12 } } } }))
      compare(widget().usage.windows["7d"].tokens, 12)
    }

    function test_quota_exit_starts_a_scan_when_on() {
      var process = usageProcess()
      widget().settings = { localUsage: true, enabledProviders: ["claude"] }
      process.running = false
      process.starts = 0
      quotaProcess().exited(0, 0)
      compare(process.running, true)
      compare(process.starts, 1)
    }

    function test_quota_exit_runs_no_scan_when_off() {
      var process = usageProcess()
      widget().settings = { localUsage: false, enabledProviders: ["claude"] }
      process.running = false
      process.starts = 0
      quotaProcess().exited(0, 0)
      compare(process.running, false)
      compare(process.starts, 0)
    }

    function test_toggle_back_on_restarts_the_scan() {
      var process = usageProcess()
      widget().settings = { localUsage: true, enabledProviders: ["claude"] }
      widget().usage = { scanning: false, windows: {} }
      process.running = false
      widget().settings = { localUsage: false, enabledProviders: ["claude"] }
      compare(widget().usage, null)
      process.starts = 0
      widget().settings = { localUsage: true, enabledProviders: ["claude"] }
      wait(50)
      compare(process.running, true)
      compare(process.starts, 1)
    }

    function test_selection_change_restarts_the_scan() {
      var process = usageProcess()
      widget().settings = { localUsage: true, enabledProviders: ["claude"] }
      process.running = false
      widget().refreshUsage()
      compare(process.running, true)
      widget().settings = { localUsage: true, enabledProviders: ["codex"] }
      compare(process.running, false)
      compare(widget().usagePending, true)
      process.exited(0, 0)
      wait(50)
      compare(process.running, true)
      compare(process.command[4], "codex")
    }

    function test_fresh_cache_starts_the_first_scan() {
      var process = usageProcess()
      widget().settings = { localUsage: true, enabledProviders: ["claude"] }
      widget().usage = null
      widget().usageSelectionKey = ""
      widget().lastAttemptMs = Date.now()
      process.running = false
      process.starts = 0
      widget().refreshIfStale()
      wait(50)
      compare(process.running, true)
      compare(process.starts, 1)
    }
  }

  TestCase {
    name: "UsageTab"
    when: windowShown

    function panel() {
      return panelLoader.item
    }

    function usageTab() {
      return harness.find(panel(), function(item) { return item.usageMessage !== undefined })
    }

    function windowSelector() {
      return harness.find(panel(), function(item) {
        return item.options !== undefined && item.options.length > 0 && item.options[0].value === "today"
      })
    }

    function tabSelector() {
      return harness.find(panel(), function(item) {
        return item.options !== undefined && item.options.length > 0 && item.options[0].value === "limits"
      })
    }

    function initTestCase() {
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.saved = []
      panelLoader.setSource(Qt.resolvedUrl("../Panel.qml"), { hostWidget: panelHost })
      verify(panel() !== null)
      verify(usageTab() !== null)
      verify(windowSelector() !== null)
      verify(tabSelector() !== null)
    }

    function test_defaults_to_limits_and_seven_days() {
      compare(panel().tab, "limits")
      compare(tabSelector().value, "limits")
      compare(windowSelector().value, "7d")
      compare(windowSelector().options[1].value, "7d")
    }

    function test_persisted_window_is_restored() {
      panelHost.settings = { usageWindow: "30d" }
      compare(windowSelector().value, "30d")
      panelHost.settings = { usageWindow: "bogus" }
      compare(windowSelector().value, "7d")
      panelHost.settings = {}
    }

    function test_window_change_is_saved() {
      panelHost.saved = []
      windowSelector().changed("today")
      compare(panelHost.saved.length, 1)
      compare(panelHost.saved[0][0], "usageWindow")
      compare(panelHost.saved[0][1], "today")
    }

    function test_toggle_hides_the_usage_tab() {
      panelHost.localUsage = false
      compare(tabSelector().visible, false)
      panelHost.localUsage = true
      compare(tabSelector().visible, true)
    }

    function test_switching_tabs() {
      tabSelector().changed("usage")
      compare(panel().tab, "usage")
      tabSelector().changed("limits")
      compare(panel().tab, "limits")
    }

    function test_no_local_usage_message() {
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude"]
      panelHost.usage = { scanning: false, windows: { "30d": { providers: [], models: [] } } }
      compare(usageTab().usageFound, false)
      compare(usageTab().usageMessage, "No local usage found")
      panelHost.usage = { scanning: false, windows: { "30d": { providers: [{ id: "claude", tokens: 5 }] } } }
      compare(usageTab().usageFound, true)
      compare(usageTab().usageMessage, "")
      panelHost.usage = { scanning: true, windows: {} }
      compare(usageTab().usageMessage, "Scanning local logs…")
      panelHost.enabledProviders = []
      compare(usageTab().usageMessage, "No providers enabled")
      panelHost.enabledProviders = ["claude"]
      panelHost.usage = { scanning: false, windows: {} }
    }
  }
}
