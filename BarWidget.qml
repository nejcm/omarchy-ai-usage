import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Owns the collector, preferences, and usage state shared with the panel.
BarWidget {
  id: root
  moduleName: "io.github.nejcm.ai-usage"

  property var rows: []
  property string refreshedAt: ""
  property bool refreshing: false
  property bool loadedOnce: false
  property double lastAttemptMs: 0
  property double cachedAtMs: 0
  property bool cacheChecked: false
  property bool refreshPending: false

  readonly property var providerOrder: Model.providerOrder(setting("providerOrder", Model.SETTING_DEFAULTS.providerOrder))
  readonly property var enabledProviders: Model.enabledInOrder(providerOrder, setting("enabledProviders", Model.SETTING_DEFAULTS.enabledProviders))
  readonly property string selectionKey: enabledProviders.join(",")
  readonly property var displayRows: Model.orderedRows(rows, enabledProviders)
  readonly property var navbarRows: Model.orderedRows(rows, Model.selectedProviders(enabledProviders, setting("hiddenProviders", Model.SETTING_DEFAULTS.hiddenProviders)))
  readonly property string displayMode: setting("displayMode", Model.SETTING_DEFAULTS.displayMode)
  readonly property bool colorWarnings: setting("colorWarnings", Model.SETTING_DEFAULTS.colorWarnings) === true
  readonly property bool desktopNotifications: setting("desktopNotifications", Model.SETTING_DEFAULTS.desktopNotifications) === true
  readonly property int warningThreshold: Model.warningThreshold(setting("warningThreshold", Model.SETTING_DEFAULTS.warningThreshold))
  readonly property int refreshMs: Model.refreshSeconds(setting("refreshIntervalSec", Model.SETTING_DEFAULTS.refreshIntervalSec)) * 1000
  readonly property string script: Qt.resolvedUrl("usage.py").toString().replace("file://", "")
  readonly property string cachePath: (Quickshell.env("XDG_CACHE_HOME") || Quickshell.env("HOME") + "/.cache") + "/omarchy-ai-usage.json"

  function writeSettings(next) {
    if (JSON.stringify(next) === JSON.stringify(root.settings)) return
    root.settings = next
    if (root.bar && root.bar.shell) root.bar.shell.updateEntryInline(root.moduleName, next)
  }

  function saveSetting(name, value) {
    var next = Object.assign({}, root.settings)
    next[name] = value
    writeSettings(next)
  }

  function resetSettings() {
    writeSettings(Model.resetSettings(root.settings))
  }

  function toggleProviderList(name, id, list) {
    list = Model.providerList(list)
    var index = list.indexOf(id)
    if (index < 0) list.push(id)
    else list.splice(index, 1)
    saveSetting(name, list)
  }

  function moveProvider(id, direction) {
    saveSetting("providerOrder", Model.moveItem(providerOrder, id, providerOrder.indexOf(id) + direction))
  }

  function moveProviderToTop(id) {
    saveSetting("providerOrder", Model.moveItem(providerOrder, id, 0))
  }

  function checkWarnings(incoming) {
    var result = Model.warningEvents(incoming, setting("warningState", {}), warningThreshold, desktopNotifications)
    saveSetting("warningState", result.state)
    for (var i = 0; i < result.events.length; i++) {
      var event = result.events[i]
      Quickshell.execDetached(["omarchy-notification-send", "AI usage: " + event.name,
        event.label + " is at " + Model.percentText(event.percent) + " used"])
    }
  }

  function refresh() {
    if (usageProcess.running) {
      refreshPending = true
      return
    }
    refreshPending = false
    if (enabledProviders.length === 0) {
      loadedOnce = true
      return
    }
    lastAttemptMs = Date.now()
    refreshing = true
    var command = ["python3", root.script]
    for (var i = 0; i < enabledProviders.length; i++) command.push("--provider", enabledProviders[i])
    usageProcess.command = command
    usageProcess.running = true
  }

  function restoreCache(text) {
    var cached = root.rows.length === 0 ? Model.restoreCache(text) : null
    if (cached && cached.rows.length > 0) {
      root.rows = cached.rows
      root.refreshedAt = cached.refreshedAt
      root.cachedAtMs = cached.refreshedMs
    }
    root.cacheChecked = true
  }

  // Timer and panel-open refreshes are interval-gated from the last attempt or a fully covered cache.
  function refreshIfStale() {
    var cachedMs = displayRows.length === enabledProviders.length ? cachedAtMs : 0
    var lastMs = Math.max(lastAttemptMs, cachedMs)
    if (lastMs === 0 || Date.now() - lastMs >= refreshMs) refresh()
  }

  function applyOutput(text) {
    refreshing = false
    // A cache write drops any in-flight read without emitting loaded/loadFailed.
    cacheChecked = true
    var parsed = null
    try {
      parsed = JSON.parse(String(text || ""))
    } catch (error) {
      parsed = null
    }
    if (!parsed || !Array.isArray(parsed.providers)) {
      if (root.rows.length > 0) root.rows = Model.markStale(root.rows)
      return
    }
    var incoming = Model.orderedRows(parsed.providers, root.enabledProviders)
    var anyOk = false
    for (var i = 0; i < incoming.length; i++) if (incoming[i].status === "ok") anyOk = true
    root.rows = Model.mergeRows(root.rows, incoming)
    if (anyOk && parsed.refreshedAt) root.refreshedAt = parsed.refreshedAt
    root.loadedOnce = true
    cacheFile.setText(JSON.stringify({ refreshedAt: root.refreshedAt, rows: root.rows }))
    root.checkWarnings(incoming)
  }

  onSelectionKeyChanged: {
    root.rows = Model.orderedRows(root.rows, root.enabledProviders)
    if (root.enabledProviders.length === 0) root.loadedOnce = true
    if (root.lastAttemptMs > 0 || root.loadedOnce) Qt.callLater(root.refresh)
    // Newly enabled providers fetch only if the fresh cache does not cover them.
    else if (root.cacheChecked) Qt.callLater(root.refreshIfStale)
  }

  Component.onCompleted: if (root.enabledProviders.length === 0) root.loadedOnce = true

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function open() {
    if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item) panelLoader.item.close()
  }

  function togglePanel() {
    if (panelLoader.item) panelLoader.item.toggle()
  }

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: usageProcess
    command: ["python3", root.script]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyOutput(text)
    }
    onExited: function(exitCode, exitStatus) {
      root.refreshing = false
      if (exitCode !== 0 && root.rows.length > 0) root.rows = Model.markStale(root.rows)
      if (root.refreshPending) Qt.callLater(root.refresh)
    }
  }

  // usage.py timeouts are per socket read; cap the whole run here.
  Timer {
    interval: 60000
    running: usageProcess.running
    onTriggered: usageProcess.running = false
  }

  FileView {
    id: cacheFile
    path: root.cachePath
    atomicWrites: true
    printErrors: false
    onLoaded: root.restoreCache(text())
    onLoadFailed: root.cacheChecked = true
  }

  Timer {
    interval: root.refreshMs
    repeat: true
    running: root.cacheChecked && root.enabledProviders.length > 0
    triggeredOnStart: true
    onTriggered: root.refreshIfStale()
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.navbarRows.length === 0 ? "AI" : ""
    labelVisible: root.navbarRows.length === 0
    hasVisualContent: true
    fixedWidth: root.navbarRows.length === 0 ? -1 : barRow.implicitWidth + scaledHorizontalMargin * 2
    dimmed: !root.loadedOnce && root.displayRows.length === 0
    tooltipText: Model.barTooltip(root.displayMode)
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.togglePanel()
    }

    Row {
      id: barRow
      anchors.centerIn: parent
      spacing: Style.space(10)

      Repeater {
        model: root.navbarRows

        delegate: Row {
          id: item
          required property var modelData
          spacing: Style.space(4)

          Image {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(1, valueText.implicitHeight - Style.space(3))
            height: width
            fillMode: Image.PreserveAspectFit
            sourceSize: Qt.size(-1, height * 2)
            source: Qt.resolvedUrl("assets/" + Model.logo(item.modelData.provider, true))
          }

          Text {
            id: valueText
            text: Model.barValue(item.modelData, root.displayMode)
            color: root.colorWarnings && Model.isWarning(item.modelData, root.warningThreshold) ? Model.usageColor(100) : button.foreground
            font.family: button.fontFamily
            font.pixelSize: button.fontSize
            renderType: Text.NativeRendering
          }
        }
      }
    }
  }
}
