import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar label plus the host for the usage panel. Owns the refresh state and the
// one-shot collector process; Panel.qml is a view onto it.
BarWidget {
  id: root
  moduleName: "io.github.nejcm.ai-usage"

  property var rows: []
  property string refreshedAt: ""
  property bool refreshing: false
  property bool loadedOnce: false
  property double lastRefreshMs: 0

  readonly property int refreshMs: Math.max(60, Number(setting("refreshIntervalSec", 300))) * 1000
  readonly property string script: Qt.resolvedUrl("usage.py").toString().replace("file://", "")

  function refresh() {
    if (usageProcess.running) return
    refreshing = true
    usageProcess.running = true
  }

  // Opening the panel refreshes only when the cache is older than the interval.
  function refreshIfStale() {
    if (!loadedOnce || Date.now() - lastRefreshMs > refreshMs) refresh()
  }

  function applyOutput(text) {
    refreshing = false
    var parsed = null
    try {
      parsed = JSON.parse(String(text || ""))
    } catch (error) {
      return
    }
    if (!parsed || !parsed.providers) return
    rows = parsed.providers
    refreshedAt = parsed.refreshedAt || ""
    lastRefreshMs = Date.now()
    loadedOnce = true
  }

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
    onExited: root.refreshing = false
  }

  Timer {
    interval: root.refreshMs
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh()
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

  IpcHandler {
    target: "io.github.nejcm.ai-usage"

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.togglePanel() }
    function refresh(): void { root.refresh() }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: Model.barText(root.rows)
    dimmed: !root.loadedOnce
    tooltipText: "AI subscription usage"
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.togglePanel()
    }
  }
}
