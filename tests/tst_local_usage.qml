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

  function collect(rootItem, predicate, out) {
    out = out || []
    if (!rootItem) return out
    if (predicate(rootItem)) out.push(rootItem)
    var data = rootItem.data || []
    for (var i = 0; i < data.length; i++) collect(data[i], predicate, out)
    return out
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
      compare(Model.USAGE_PROVIDERS, ["claude", "codex", "opencode"])
      compare(Model.localUsageProviders(["codex", "cursor", "claude"]), ["claude", "codex"])
      compare(Model.localUsageProviders([]), [])
      compare(Model.localUsageProviders(undefined), [])
      compare(Model.providerSummary({ providers: [{ id: "codex", tokens: 3 }] }, "codex").tokens, 3)
      verify(Model.providerSummary({ providers: [] }, "codex") === null)
      verify(Model.providerSummary(null, "codex") === null)
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

    function toolSelector() {
      return harness.find(panel(), function(item) {
        return item.options !== undefined && item.options.length > 0 && item.options[0].value === "" && item.options[0].label === "All"
      })
    }

    function keyCatcher() {
      return harness.find(panel(), function(item) { return typeof item.moveRequested === "function" && typeof item.tabRequested === "function" })
    }

    function usageButton(text) {
      return harness.find(usageTab(), function(item) { return item.text === text })
    }

    function modelsButton() {
      return harness.find(usageTab(), function(item) {
        return typeof item.text === "string" && (item.text.indexOf(" more") >= 0 || item.text === "Show less")
      })
    }

    function modelRows() {
      return harness.collect(usageTab(), function(item) {
        return item.modelData !== undefined && item.modelData !== null &&
               typeof item.modelData.name === "string" && typeof item.modelData.provider === "string"
      })
    }

    function visibleModelRows() {
      var rows = modelRows()
      var out = []
      for (var i = 0; i < rows.length; i++) if (rows[i].visible) out.push(rows[i])
      return out
    }

    function usageFixture() {
      var models = [
        { name: "claude-opus-5", provider: "claude", tokens: 100 },
        { name: "gpt-6.1-sol", provider: "codex", tokens: 80 },
        { name: "claude-sonnet-4", provider: "claude", tokens: 30 },
        { name: "gpt-5", provider: "codex", tokens: 10 },
        { name: "claude-mid", provider: "claude", tokens: 5 },
        { name: "claude-tiny", provider: "claude", tokens: 2 },
        { name: "claude-small-1", provider: "claude", tokens: 1 },
        { name: "claude-small-2", provider: "claude", tokens: 1 },
        { name: "claude-small-3", provider: "claude", tokens: 1 }
      ]
      var days = [
        { date: "2026-10-06", providers: { claude: 0, codex: 0 } },
        { date: "2026-10-07", providers: { claude: 0, codex: 0 } },
        { date: "2026-10-08", providers: { claude: 0, codex: 0 } },
        { date: "2026-10-09", providers: { claude: 20, codex: 10 } },
        { date: "2026-10-10", providers: { claude: 0, codex: 0 } },
        { date: "2026-10-11", providers: { claude: 0, codex: 0 } },
        { date: "2026-10-12", providers: { claude: 100, codex: 60 } }
      ]
      var claude = { id: "claude", tokens: 140, output: 40, sessions: 2, cacheHit: 200 / 300,
                     breakdown: { input: 100, cacheRead: 200, cacheWrite: 0, output: 30, reasoning: 10 } }
      var codex = { id: "codex", tokens: 90, output: 30, sessions: 1, cacheHit: 50 / 110,
                    breakdown: { input: 60, cacheRead: 50, cacheWrite: 0, output: 20, reasoning: 10 } }
      var week = { tokens: 230, output: 70, sessions: 3, cacheHit: 250 / 410,
                   breakdown: { input: 160, cacheRead: 250, cacheWrite: 0, output: 50, reasoning: 20 },
                   providers: [claude, codex], models: models, days: days }
      return {
        scanning: false,
        windows: {
          today: {
            tokens: 20, output: 10, sessions: 2, cacheHit: 2 / 13,
            breakdown: { input: 10, cacheRead: 2, cacheWrite: 1, output: 5, reasoning: 5 },
            providers: [
              { id: "claude", tokens: 12, output: 7, sessions: 1, cacheHit: 2 / 8,
                breakdown: { input: 5, cacheRead: 2, cacheWrite: 1, output: 3, reasoning: 4 } },
              { id: "codex", tokens: 8, output: 3, sessions: 1, cacheHit: 0.0,
                breakdown: { input: 5, cacheRead: 0, cacheWrite: 0, output: 2, reasoning: 1 } }
            ],
            models: [
              { name: "claude-opus-5", provider: "claude", tokens: 10 },
              { name: "codex-6.1-sol", provider: "codex", tokens: 8 },
              { name: "claude-sonnet-4", provider: "claude", tokens: 2 }
            ]
          },
          "7d": week,
          "30d": week
        }
      }
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
      verify(toolSelector() !== null)
      verify(keyCatcher() !== null)
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
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude"]
      panelHost.usage = { scanning: false, windows: { "30d": { providers: [], models: [] } } }
      compare(usageTab().usageFound, false)
      compare(usageTab().usageOnboarding, true)
      compare(usageTab().usageMessage, "No local usage in the last 30 days. Claude Code, Codex, and OpenCode write the logs this tab reads.")
      panelHost.usage = { scanning: false, windows: { "30d": { providers: [{ id: "claude", tokens: 5, breakdown: {} }] } } }
      compare(usageTab().usageFound, true)
      compare(usageTab().usageOnboarding, false)
      compare(usageTab().usageMessage, "")
      panelHost.usage = { scanning: true, windows: {} }
      compare(usageTab().usageMessage, "Scanning local logs…")
      panelHost.enabledProviders = []
      compare(usageTab().usageMessage, "No providers enabled")
      panelHost.enabledProviders = ["claude"]
      panelHost.usage = { scanning: false, windows: {} }
    }

    function test_models_expand_collapse_and_reset() {
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude", "codex"]
      panelHost.usage = usageFixture()
      tabSelector().changed("usage")
      panel().showSettings(false)
      usageTab().usageFilter = ""
      wait(0)
      compare(usageTab().modelsExpanded, false)
      compare(modelRows().length, 9)
      compare(visibleModelRows().length, 5)
      compare(modelsButton().text, "4 more")

      modelsButton().clicked()
      compare(usageTab().modelsExpanded, true)
      compare(visibleModelRows().length, 9)
      compare(modelsButton().text, "Show less")

      modelsButton().clicked()
      compare(usageTab().modelsExpanded, false)
      compare(visibleModelRows().length, 5)

      windowSelector().changed("today")
      wait(0)
      compare(usageTab().modelsExpanded, false)
      compare(visibleModelRows().length, 3)

      usageTab().modelsExpanded = true
      toolSelector().changed("claude")
      compare(usageTab().modelsExpanded, false)
      compare(visibleModelRows().length, 2)
      windowSelector().changed("7d")
      toolSelector().changed("")
      wait(0)
    }

    function test_tool_filter_binds_whole_view() {
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude", "codex"]
      panelHost.usage = usageFixture()
      tabSelector().changed("usage")
      panel().showSettings(false)
      usageTab().usageFilter = ""
      wait(0)
      var usage = usageTab()
      compare(usage.usageTool, "")
      compare(usage.usageSummary.tokens, 230)
      compare(usage.usageSummary.output, 70)
      compare(usage.usageSummary.sessions, 3)
      compare(usage.usageSummary.cacheHit, 250 / 410)
      compare(usage.usageBreakdownTotal, 480)
      compare(Model.dayMax(usage.usageDays, usage.usageProviderIds), 160)
      compare(usage.usageVisibleProviders.length, 2)
      compare(usage.usageVisibleModels.length, 9)

      toolSelector().changed("claude")
      compare(usage.usageFilter, "claude")
      compare(usage.usageTool, "claude")
      compare(usage.usageSummary.tokens, 140)
      compare(usage.usageSummary.output, 40)
      compare(usage.usageSummary.sessions, 2)
      compare(usage.usageSummary.cacheHit, 200 / 300)
      compare(usage.usageBreakdown.input, 100)
      compare(usage.usageBreakdownTotal, 340)
      compare(usage.usageProviderIds.length, 1)
      compare(usage.usageProviderIds[0], "claude")
      compare(Model.dayMax(usage.usageDays, usage.usageProviderIds), 100)
      compare(usage.usageVisibleProviders.length, 1)
      compare(usage.usageVisibleProviders[0].id, "claude")
      compare(usage.usageVisibleModels.length, 7)

      windowSelector().changed("today")
      wait(0)
      compare(usage.usageWindowName, "today")
      compare(usage.usageTool, "claude")
      compare(usage.usageSummary.tokens, 12)
      compare(usage.usageSummary.output, 7)
      compare(usage.usageSummary.sessions, 1)
      compare(usage.usageSummary.cacheHit, 2 / 8)
      compare(usage.usageBreakdownTotal, 15)
      compare(usage.usageProviderIds[0], "claude")
      compare(usage.usageVisibleModels.length, 2)

      toolSelector().changed("")
      compare(usage.usageSummary.tokens, 20)
      compare(usage.usageSummary.cacheHit, 2 / 13)
      compare(usage.usageVisibleModels.length, 3)

      windowSelector().changed("30d")
      wait(0)
      compare(usage.usageWindowName, "30d")
      compare(usage.usageSummary.tokens, 230)
      compare(usage.usageSummary.cacheHit, 250 / 410)
    }

    function test_disabled_tool_falls_back_to_all() {
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude", "codex"]
      panelHost.usage = usageFixture()
      tabSelector().changed("usage")
      panel().showSettings(false)
      usageTab().usageFilter = ""
      wait(0)
      compare(toolSelector().options.length, 3)
      compare(toolSelector().options[1].label, "Claude Code")
      compare(toolSelector().options[2].label, "Codex")

      toolSelector().changed("codex")
      compare(usageTab().usageFilter, "codex")
      compare(toolSelector().value, "codex")
      panelHost.enabledProviders = ["claude"]
      wait(0)
      compare(usageTab().usageFilter, "")
      compare(usageTab().usageTool, "")
      compare(toolSelector().value, "")
      compare(toolSelector().options.length, 2)
      compare(usageTab().usageSummary.tokens, 230)
    }

    function test_tool_without_data_offers_all_and_onboarding_opens_settings() {
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude", "codex"]
      panelHost.usage = {
        scanning: false,
        windows: {
          "7d": { tokens: 140, output: 40, sessions: 2, cacheHit: 200 / 300,
                  breakdown: { input: 100, cacheRead: 200, cacheWrite: 0, output: 30, reasoning: 10 },
                  providers: [{ id: "claude", tokens: 140, output: 40, sessions: 2, cacheHit: 200 / 300,
                                breakdown: { input: 100, cacheRead: 200, cacheWrite: 0, output: 30, reasoning: 10 } }],
                  models: [{ name: "claude-opus-5", provider: "claude", tokens: 140 }],
                  days: [{ date: "2026-10-12", providers: { claude: 140 } }] },
          "30d": { tokens: 140, output: 40, sessions: 2, cacheHit: 200 / 300,
                   breakdown: { input: 100, cacheRead: 200, cacheWrite: 0, output: 30, reasoning: 10 },
                   providers: [{ id: "claude", tokens: 140, output: 40, sessions: 2, cacheHit: 200 / 300,
                                 breakdown: { input: 100, cacheRead: 200, cacheWrite: 0, output: 30, reasoning: 10 } }],
                   models: [], days: [] }
        }
      }
      tabSelector().changed("usage")
      panel().showSettings(false)
      usageTab().usageFilter = ""
      wait(0)
      toolSelector().changed("codex")
      compare(usageTab().usageFilter, "codex")
      compare(usageTab().usageFound, true)
      compare(usageTab().usageToolFound, false)
      compare(usageTab().usageToolEmpty, true)
      compare(usageTab().usageMessage, "Codex has no local usage in the last 30 days")
      compare(usageButton("Show all").visible, true)
      compare(usageButton("Open settings").visible, false)
      compare(usageTab().usageVisibleProviders.length, 0)
      compare(usageTab().usageVisibleModels.length, 0)

      usageButton("Show all").clicked()
      compare(usageTab().usageFilter, "")
      compare(usageTab().usageMessage, "")
      compare(usageTab().usageVisibleModels.length, 1)

      panelHost.usage = { scanning: false, windows: { "30d": { providers: [], models: [] } } }
      wait(0)
      compare(usageTab().usageOnboarding, true)
      compare(usageButton("Show all").visible, false)
      compare(usageButton("Open settings").visible, true)
      panel().showSettings(false)
      usageButton("Open settings").clicked()
      compare(panel().settingsOpen, true)
      panel().showSettings(false)
      compare(panel().settingsOpen, false)
      panelHost.enabledProviders = ["claude"]
      panelHost.usage = { scanning: false, windows: {} }
    }

    function test_usage_cursor_keyboard_reaches_controls() {
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude", "codex"]
      panelHost.usage = usageFixture()
      tabSelector().changed("usage")
      panel().showSettings(false)
      usageTab().usageFilter = ""
      wait(0)
      var usage = usageTab()
      compare(usage.cursorActive, false)
      keyCatcher().forceActiveFocus()
      compare(keyCatcher().activeFocus, true)

      keyClick(Qt.Key_J)
      compare(usage.cursorActive, true)
      compare(usage.cursorStop, 0)
      compare(windowSelector().cursorIndex, 1)

      keyClick(Qt.Key_J)
      compare(usage.cursorStop, 1)
      compare(toolSelector().cursorIndex, 0)

      keyClick(Qt.Key_L)
      compare(usage.cursorChip, 1)
      compare(toolSelector().cursorIndex, 1)

      keyClick(Qt.Key_Space)
      compare(usage.usageFilter, "claude")
      compare(usage.usageTool, "claude")
      compare(usage.cursorActive, false)

      keyClick(Qt.Key_J)
      keyClick(Qt.Key_J)
      keyClick(Qt.Key_J)
      compare(usage.cursorStop, 2)
      compare(modelsButton().hasCursor, true)
      keyClick(Qt.Key_Return)
      compare(usage.modelsExpanded, true)
      compare(visibleModelRows().length, 7)

      keyClick(Qt.Key_H)
      keyClick(Qt.Key_K)
      compare(usage.cursorStop, 0)
      compare(usage.cursorChip, 1)
      keyClick(Qt.Key_L)
      compare(usage.cursorChip, 2)
      keyClick(Qt.Key_Return)
      compare(windowSelector().value, "30d")
      compare(panelHost.settings.usageWindow, "30d")
      usage.resetView()
      windowSelector().changed("7d")
      panelHost.enabledProviders = ["claude"]
      wait(0)
    }

    function test_usage_cursor_activates_onboarding_button() {
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude"]
      panelHost.usage = { scanning: false, windows: { "30d": { providers: [], models: [] } } }
      tabSelector().changed("usage")
      panel().showSettings(false)
      wait(0)
      var usage = usageTab()
      compare(usage.usageOnboarding, true)
      keyCatcher().forceActiveFocus()
      keyClick(Qt.Key_J)
      keyClick(Qt.Key_J)
      keyClick(Qt.Key_J)
      compare(usage.cursorStop, 2)
      compare(usageButton("Open settings").hasCursor, true)
      keyClick(Qt.Key_Return)
      compare(panel().settingsOpen, true)
      panel().showSettings(false)
      usage.resetView()
      panelHost.usage = { scanning: false, windows: {} }
    }

    function test_tab_and_escape_dispatch_from_normal_focus() {
      panelHost.settings = {}
      panelHost.localUsage = true
      tabSelector().changed("usage")
      panel().showSettings(false)
      var calls = []
      panel().bar = {
        barForeground: "#ffffff",
        fontFamily: "monospace",
        switchPanelFrom: function (identity, direction) { calls.push(direction); return true }
      }
      keyCatcher().forceActiveFocus()
      keyClick(Qt.Key_Tab)
      compare(calls.length, 1)
      compare(calls[0], 1)
      keyClick(Qt.Key_Backtab)
      compare(calls.length, 2)
      compare(calls[1], -1)
      panel().opened = true
      keyClick(Qt.Key_Return)
      compare(panel().settingsOpen, true)
      panel().showSettings(false)
      keyClick(Qt.Key_Escape)
      compare(panel().opened, false)
      panel().bar = null
    }

    function test_filter_and_expansion_reset_on_reopen() {
      panelHost.settings = {}
      panelHost.localUsage = true
      panelHost.enabledProviders = ["claude", "codex"]
      panelHost.usage = usageFixture()
      tabSelector().changed("usage")
      panel().showSettings(false)
      usageTab().usageFilter = ""
      wait(0)
      toolSelector().changed("codex")
      usageTab().modelsExpanded = true
      compare(usageTab().usageFilter, "codex")
      compare(usageTab().modelsExpanded, true)

      tabSelector().changed("limits")
      panel().showSettings(true)
      panel().showSettings(false)
      tabSelector().changed("usage")
      compare(usageTab().usageFilter, "codex")
      compare(usageTab().modelsExpanded, true)

      panel().close()
      panel().open()
      compare(usageTab().usageFilter, "")
      compare(usageTab().modelsExpanded, false)
      compare(usageTab().cursorActive, false)
      compare(panel().tab, "limits")
      tabSelector().changed("usage")
      wait(0)
      compare(usageTab().usageTool, "")
      panelHost.enabledProviders = ["claude"]
    }
  }
}
