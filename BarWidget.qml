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
  property double lastAttemptMs: 0

  readonly property int refreshMs: Math.max(300, Number(setting("refreshIntervalSec", 300))) * 1000
  readonly property string script: Qt.resolvedUrl("usage.py").toString().replace("file://", "")

  function refresh() {
    if (usageProcess.running) return
    lastAttemptMs = Date.now()
    refreshing = true
    usageProcess.running = true
  }

  // Timer and panel-open refreshes are interval-gated; only refresh() is ungated.
  function refreshIfStale() {
    if (!loadedOnce || Date.now() - lastAttemptMs >= refreshMs) refresh()
  }

  function applyOutput(text) {
    refreshing = false
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
    var incoming = parsed.providers
    var anyOk = false
    for (var i = 0; i < incoming.length; i++) if (incoming[i].status === "ok") anyOk = true
    root.rows = Model.mergeRows(root.rows, incoming)
    if (anyOk && parsed.refreshedAt) root.refreshedAt = parsed.refreshedAt
    root.loadedOnce = true
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
    onExited: function(exitCode, exitStatus) {
      root.refreshing = false
      if (exitCode !== 0 && root.rows.length > 0) root.rows = Model.markStale(root.rows)
    }
  }

  Timer {
    interval: root.refreshMs
    repeat: true
    running: true
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
    text: Model.barText(root.rows)
    dimmed: !root.loadedOnce
    tooltipText: "AI subscription usage"
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.togglePanel()
    }
  }
}
