import QtQuick
import QtQuick.Window
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Details panel: one card per provider, one meter per metric. All state lives
// on the bar widget injected as hostWidget.
Panel {
  id: root
  moduleName: "io.github.nejcm.ai-usage"
  ipcTarget: "io.github.nejcm.ai-usage"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property double nowMs: Date.now()
  property bool settingsOpen: false
  property string tab: "limits"
  property bool breakdownOpen: false
  readonly property var barIdentity: hostWidget || root

  readonly property var rows: hostWidget ? hostWidget.displayRows : []
  readonly property bool refreshing: hostWidget ? hostWidget.refreshing : false
  readonly property string refreshedAt: hostWidget ? hostWidget.refreshedAt : ""
  readonly property bool localUsage: hostWidget ? hostWidget.localUsage === true : false
  readonly property var usage: hostWidget ? hostWidget.usage : null
  readonly property string usageWindowName: Model.usageWindowName(hostWidget ? hostWidget.setting("usageWindow", Model.SETTING_DEFAULTS.usageWindow) : Model.SETTING_DEFAULTS.usageWindow)
  readonly property var usageWindow: usage && usage.windows ? (usage.windows[usageWindowName] || usage.windows["7d"] || null) : null
  readonly property var usageProviders: usageWindow && usageWindow.providers ? usageWindow.providers : []
  readonly property var usageModels: usageWindow && usageWindow.models ? usageWindow.models : []
  readonly property var usageDays: usageWindow && usageWindow.days ? usageWindow.days : []
  readonly property var usageProviderIds: Model.providerIds(usageWindow)
  readonly property bool usageScanning: usage !== null && usage.scanning === true
  readonly property bool usageFound: {
    var month = usage && usage.windows ? usage.windows["30d"] : null
    return !!month && Array.isArray(month.providers) && month.providers.length > 0
  }
  readonly property string usageMessage: {
    if (hostWidget && hostWidget.enabledProviders && hostWidget.enabledProviders.length === 0) return "No providers enabled"
    if (!usage || usageScanning) return "Scanning local logs…"
    return usageFound ? "" : "No local usage found"
  }
  readonly property real usageBreakdownTotal: {
    var breakdown = usageWindow && usageWindow.breakdown ? usageWindow.breakdown : null
    return breakdown ? Number(breakdown.input) + Number(breakdown.cacheRead) + Number(breakdown.cacheWrite) + Number(breakdown.output) + Number(breakdown.reasoning) : 0
  }
  readonly property color contentForeground: bar ? bar.barForeground : Color.foreground
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color dimForeground: Qt.darker(contentForeground, 1.5)

  function open() {
    root.settingsOpen = false
    root.tab = "limits"
    root.nowMs = Date.now()
    if (hostWidget && hostWidget.refreshIfStale)
      hostWidget.refreshIfStale()
    root.controller.show()
  }

  function showSettings(show) {
    root.settingsOpen = show
    scroll.contentY = 0
    backButton.forceActiveFocus()
  }

  onOpenedChanged: if (!opened)
    root.settingsOpen = false

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  component SectionLabel: Text {
    color: root.contentForeground
    font.family: root.contentFontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
    textFormat: Text.PlainText
  }

  component StatCell: Column {
    id: cell
    required property string label
    required property string value
    spacing: Style.space(2)

    Text {
      text: cell.value
      color: root.contentForeground
      font.family: root.contentFontFamily
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    Text {
      text: cell.label
      color: root.dimForeground
      font.family: root.contentFontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // Keeps the reset countdowns live; Date.now() alone gives no binding dependency.
  Timer {
    interval: 30000
    repeat: true
    running: root.opened
    onTriggered: root.nowMs = Date.now()
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(header.height + Style.space(32) + (root.settingsOpen ? settingsContent.implicitHeight : content.implicitHeight), Math.floor(panel.screenH * 0.6))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: root.settingsOpen
      Keys.onEscapePressed: root.close()
      onCloseRequested: root.close()
      onTabRequested: function (direction) {
        root.switchPanel(direction)
      }
      onActivateRequested: root.showSettings(true)

      Column {
        anchors.fill: parent
        width: parent.width
        spacing: Style.space(16)

        Item {
          id: header
          width: parent.width
          height: Math.max(titleColumn.implicitHeight, headerActions.implicitHeight)

          Column {
            id: titleColumn
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(4)

            Text {
              text: root.settingsOpen ? "Settings" : "AI subscription usage"
              color: root.contentForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
            }

            Text {
              id: updatedText
              visible: !root.settingsOpen && (root.refreshedAt !== "" || root.refreshing)
              text: root.refreshing ? "refreshing…" : "Updated " + Model.updatedText(root.refreshedAt, root.nowMs)
              color: root.dimForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.caption

              HoverHandler {
                id: updatedHover
              }

              PanelToolTip {
                visible: updatedHover.hovered && !root.refreshing && Model.clockText(root.refreshedAt) !== ""
                text: "Updated at " + Model.clockText(root.refreshedAt)
                fontFamily: root.contentFontFamily
              }
            }
          }

          Row {
            id: headerActions
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(4)
            PanelActionButton {
              iconText: "󰑐"
              tooltipText: "Refresh now"
              visible: !root.settingsOpen
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              focusable: true
              onClicked: if (root.hostWidget && root.hostWidget.refresh) root.hostWidget.refresh()
            }
            PanelActionButton {
              id: backButton
              iconText: root.settingsOpen ? "←" : "󰒓"
              tooltipText: root.settingsOpen ? "Back to usage" : "Settings"
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              focusable: true
              onClicked: root.showSettings(!root.settingsOpen)
            }
            PanelActionButton {
              iconText: "×"
              tooltipText: "Close"
              fontSize: Style.font.icon + 3
              size: Math.max(Style.space(22), Style.font.icon + Style.spacing.sm * 2)
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              focusable: true
              onClicked: root.close()
            }
          }
        }

        PanelSeparator {
          foreground: root.contentForeground
        }

        Flickable {
          id: scroll
          width: parent.width
          height: Math.max(0, parent.height - y)
          contentWidth: width
          contentHeight: root.settingsOpen ? settingsContent.implicitHeight : content.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          Loader {
            id: settingsContent
            width: scroll.width
            visible: root.settingsOpen
            active: root.hostWidget !== null
            sourceComponent: Settings {
              hostWidget: root.hostWidget
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
            }
          }

          Column {
            id: content
            width: scroll.width
            visible: !root.settingsOpen
            spacing: Style.space(16)

            ButtonGroup {
              visible: root.localUsage
              width: parent.width
              options: [
                { value: "limits", label: "Limits" },
                { value: "usage", label: "Usage" }
              ]
              value: root.tab
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              onChanged: function (value) {
                root.tab = value
              }
            }

            Column {
              id: limitsTab
              width: parent.width
              visible: !root.localUsage || root.tab === "limits"
              spacing: Style.space(16)

              Text {
                visible: root.rows.length === 0
                width: parent.width
                text: root.hostWidget && root.hostWidget.enabledProviders.length === 0 ? "No providers enabled" : root.refreshing ? "Loading…" : "No usage data yet"
                color: root.dimForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.body
              }

              Button {
                visible: root.hostWidget && root.hostWidget.enabledProviders.length === 0
                text: "Open settings"
                foreground: root.contentForeground
                fontFamily: root.contentFontFamily
                focusable: true
                onClicked: root.showSettings(true)
              }

              Repeater {
                model: root.rows

                delegate: Column {
                  id: card
                  required property var modelData
                  width: content.width
                  spacing: Style.space(4)

                  Item {
                    width: parent.width
                    height: nameText.implicitHeight

                    Image {
                      id: nameLogo
                      anchors.left: parent.left
                      anchors.verticalCenter: nameText.verticalCenter
                      width: nameText.implicitHeight
                      height: width
                      fillMode: Image.PreserveAspectFit
                      sourceSize: Qt.size(-1, height * 2)
                      source: Qt.resolvedUrl("assets/" + Model.panelLogo(card.modelData.provider))
                    }

                    Text {
                      id: nameText
                      anchors.left: nameLogo.right
                      anchors.leftMargin: Style.space(8)
                      text: card.modelData.name
                      color: root.contentForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.subtitle
                      font.bold: true
                    }

                    Text {
                      anchors.right: parent.right
                      anchors.verticalCenter: nameText.verticalCenter
                      text: Model.planText(card.modelData)
                      color: root.dimForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }

                  Text {
                    id: statusLine
                    visible: Model.statusText(card.modelData) !== ""
                    width: parent.width
                    text: Model.statusText(card.modelData)
                    color: root.dimForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap

                    HoverHandler {
                      id: statusHover
                    }

                    PanelToolTip {
                      visible: statusHover.hovered && Model.statusDetail(card.modelData) !== statusLine.text
                      text: Model.statusDetail(card.modelData)
                      fontFamily: root.contentFontFamily
                    }
                  }

                  Text {
                    visible: Model.statusHint(card.modelData) !== ""
                    width: parent.width
                    text: Model.statusHint(card.modelData)
                    color: root.dimForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }

                  Repeater {
                    model: card.modelData.metrics

                    delegate: Column {
                      id: metric
                      required property var modelData
                      width: card.width
                      spacing: Style.space(4)

                      Item {
                        width: parent.width
                        height: metricLabel.implicitHeight

                        Text {
                          id: metricLabel
                          anchors.left: parent.left
                          text: metric.modelData.label
                          color: root.contentForeground
                          font.family: root.contentFontFamily
                          font.pixelSize: Style.font.caption
                        }

                        Text {
                          anchors.right: parent.right
                          anchors.verticalCenter: metricLabel.verticalCenter
                          text: Model.percentText(metric.modelData.percent) + " used"
                          color: root.hostWidget && root.hostWidget.colorWarnings && Number(metric.modelData.percent) >= root.hostWidget.warningThreshold ? Model.usageColor(100) : root.contentForeground
                          font.family: root.contentFontFamily
                          font.pixelSize: Style.font.caption
                        }
                      }

                      Item {
                        id: meter
                        width: parent.width
                        height: Style.space(7)
                        readonly property real gap: Style.space(3)
                        readonly property real fillWidth: Math.round(width * Math.min(1, Math.max(0, Number(metric.modelData.percent || 0) / 100)))
                        readonly property color fillColor: root.hostWidget && root.hostWidget.colorWarnings && Number(metric.modelData.percent) >= root.hostWidget.warningThreshold ? Model.usageColor(100) : Model.usageColor(metric.modelData.percent)

                        Rectangle {
                          width: meter.fillWidth
                          height: parent.height
                          radius: Style.space(2)
                          gradient: Gradient {
                            orientation: Gradient.Vertical
                            GradientStop { position: 0; color: Qt.lighter(meter.fillColor, 1.12) }
                            GradientStop { position: 1; color: Qt.darker(meter.fillColor, 1.08) }
                          }

                          Behavior on width {
                            NumberAnimation {
                              duration: 250
                              easing.type: Easing.OutCubic
                            }
                          }
                        }

                        Rectangle {
                          x: meter.fillWidth > 0 ? meter.fillWidth + meter.gap : 0
                          width: Math.max(0, meter.width - x)
                          height: parent.height
                          radius: Style.space(2)
                          color: Qt.rgba(root.contentForeground.r, root.contentForeground.g, root.contentForeground.b, 0.12)
                        }

                        Rectangle {
                          readonly property real elapsed: Model.elapsedFraction(metric.modelData, root.nowMs)
                          visible: elapsed >= 0
                          x: Math.min(meter.width - width, Math.max(0, Math.round(meter.width * elapsed) - width / 2))
                          y: -Style.space(2)
                          width: Style.space(2)
                          height: parent.height + Style.space(4)
                          color: "white"
                        }
                      }

                      Text {
                        visible: metric.modelData.resetsAt !== ""
                        text: "resets in " + Model.resetText(metric.modelData.resetsAt, root.nowMs)
                        color: root.dimForeground
                        font.family: root.contentFontFamily
                        font.pixelSize: Style.font.caption
                      }
                    }
                  }
                }
              }

              Button {
                visible: Model.anyNeedsSignIn(root.rows)
                text: "Troubleshooting"
                iconText: "↗"
                tooltipText: Model.TROUBLESHOOTING_URL
                foreground: root.contentForeground
                fontFamily: root.contentFontFamily
                focusable: true
                onClicked: Qt.openUrlExternally(Model.TROUBLESHOOTING_URL)
              }
            }

            Column {
              id: usageTab
              width: parent.width
              visible: root.localUsage && root.tab === "usage"
              spacing: Style.space(12)

              ButtonGroup {
                width: parent.width
                options: [
                  { value: "today", label: "Today" },
                  { value: "7d", label: "7D" },
                  { value: "30d", label: "30D" }
                ]
                value: root.usageWindowName
                foreground: root.contentForeground
                fontFamily: root.contentFontFamily
                onChanged: function (value) {
                  if (root.hostWidget) root.hostWidget.saveSetting("usageWindow", value)
                }
              }

              Text {
                visible: root.usageMessage !== ""
                width: parent.width
                text: root.usageMessage
                color: root.dimForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.body
              }

              Row {
                visible: root.usageWindow !== null && root.usageFound
                spacing: Style.space(16)

                StatCell { label: "tokens"; value: Model.compactNumber(root.usageWindow ? root.usageWindow.tokens : 0) }
                StatCell { label: "output"; value: Model.compactNumber(root.usageWindow ? root.usageWindow.output : 0) }
                StatCell { label: "sessions"; value: String(root.usageWindow ? root.usageWindow.sessions : 0) }
                StatCell { label: "cache hit"; value: Model.percentText(100 * Number(root.usageWindow ? root.usageWindow.cacheHit : 0)) }
              }

              Column {
                visible: root.usageDays.length > 0 && root.usageFound
                width: parent.width
                spacing: Style.space(2)

                Item {
                  id: dayChart
                  width: parent.width
                  height: Style.space(64)

                  Row {
                    id: dayBars
                    anchors.fill: parent
                    spacing: Style.space(2)
                    readonly property real max: Model.dayMax(root.usageDays, root.usageProviderIds)

                    Repeater {
                      model: root.usageDays
                      delegate: Item {
                        id: dayBar
                        required property var modelData
                        width: (dayBars.width - dayBars.spacing * (root.usageDays.length - 1)) / root.usageDays.length
                        height: dayBars.height

                        Repeater {
                          model: root.usageProviderIds
                          delegate: Rectangle {
                            required property string modelData
                            required property int index
                            readonly property real tokens: Model.dayProviderTokens(dayBar.modelData, modelData)
                            width: dayBar.width
                            height: tokens / Math.max(1, dayBars.max) * dayBar.height
                            y: dayBar.height - (Model.stackOffset(dayBar.modelData, root.usageProviderIds, index) / Math.max(1, dayBars.max) * dayBar.height) - height
                            visible: tokens > 0
                            color: Model.providerColor(modelData)
                          }
                        }
                      }
                    }
                  }
                }

                Item {
                  width: parent.width
                  height: dayAxisLeft.implicitHeight

                  Text {
                    id: dayAxisLeft
                    anchors.left: parent.left
                    text: root.usageDays.length > 0 ? Model.dayLabel(root.usageDays[0].date) : ""
                    color: root.dimForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.usageDays.length > 0 ? Model.dayLabel(root.usageDays[Math.floor(root.usageDays.length / 2)].date) : ""
                    color: root.dimForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    anchors.right: parent.right
                    text: "now"
                    color: root.dimForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }

              Column {
                visible: root.usageProviders.length > 0
                width: parent.width
                spacing: Style.space(6)

                SectionLabel { text: "Tokens by tool" }

                Repeater {
                  model: root.usageProviders
                  delegate: Item {
                    id: toolRow
                    required property var modelData
                    width: parent.width
                    height: Math.max(toolName.implicitHeight, toolValue.implicitHeight)

                    Rectangle {
                      id: toolDot
                      anchors.verticalCenter: parent.verticalCenter
                      width: Style.space(8)
                      height: width
                      radius: width / 2
                      color: Model.providerColor(toolRow.modelData.id)
                    }

                    Text {
                      id: toolName
                      anchors.left: toolDot.right
                      anchors.leftMargin: Style.space(8)
                      anchors.right: toolTrack.left
                      anchors.rightMargin: Style.space(8)
                      anchors.verticalCenter: parent.verticalCenter
                      text: Model.PROVIDER_INFO[toolRow.modelData.id] ? Model.PROVIDER_INFO[toolRow.modelData.id].name : toolRow.modelData.id
                      textFormat: Text.PlainText
                      elide: Text.ElideRight
                      color: root.contentForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.caption
                    }

                    Text {
                      id: toolValue
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      text: Model.compactNumber(toolRow.modelData.tokens)
                      color: root.contentForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.caption
                    }

                    Rectangle {
                      id: toolTrack
                      anchors.right: toolValue.left
                      anchors.rightMargin: Style.space(8)
                      anchors.verticalCenter: parent.verticalCenter
                      width: parent.width * 0.3
                      height: Style.space(4)
                      radius: height / 2
                      color: Qt.rgba(root.contentForeground.r, root.contentForeground.g, root.contentForeground.b, 0.12)

                      Rectangle {
                        width: toolRow.modelData.tokens / Math.max(1, root.usageProviders[0].tokens) * parent.width
                        height: parent.height
                        radius: parent.radius
                        color: Model.providerColor(toolRow.modelData.id)
                      }
                    }
                  }
                }
              }

              Column {
                visible: root.usageModels.length > 0
                width: parent.width
                spacing: Style.space(6)

                SectionLabel { text: "Tokens by model" }

                Repeater {
                  model: root.usageModels
                  delegate: Column {
                    id: modelRow
                    required property var modelData
                    required property int index
                    width: parent.width
                    spacing: Style.space(2)
                    visible: index < 5

                    Item {
                      width: parent.width
                      height: modelName.implicitHeight

                      Rectangle {
                        id: modelDot
                        anchors.verticalCenter: parent.verticalCenter
                        width: Style.space(8)
                        height: width
                        radius: width / 2
                        color: Model.providerColor(modelRow.modelData.provider)
                      }

                      Rectangle {
                        id: modelTrack
                        anchors.right: modelValue.left
                        anchors.rightMargin: Style.space(8)
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width * 0.3
                        height: Style.space(4)
                        radius: height / 2
                        color: Qt.rgba(root.contentForeground.r, root.contentForeground.g, root.contentForeground.b, 0.12)

                        Rectangle {
                          width: modelRow.modelData.tokens / Math.max(1, root.usageModels[0].tokens) * parent.width
                          height: parent.height
                          radius: parent.radius
                          color: Model.providerColor(modelRow.modelData.provider)
                        }
                      }

                      Text {
                        id: modelName
                        anchors.left: modelDot.right
                        anchors.leftMargin: Style.space(8)
                        anchors.right: modelTrack.left
                        anchors.rightMargin: Style.space(8)
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelRow.modelData.name
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        color: root.contentForeground
                        font.family: root.contentFontFamily
                        font.pixelSize: Style.font.caption
                      }

                      Text {
                        id: modelValue
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: Model.compactNumber(modelRow.modelData.tokens)
                        color: root.contentForeground
                        font.family: root.contentFontFamily
                        font.pixelSize: Style.font.caption
                      }
                    }

                    Text {
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(16)
                      anchors.right: parent.right
                      text: Model.PROVIDER_INFO[modelRow.modelData.provider] ? Model.PROVIDER_INFO[modelRow.modelData.provider].name : modelRow.modelData.provider
                      textFormat: Text.PlainText
                      elide: Text.ElideRight
                      color: root.dimForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                }

                Text {
                  visible: root.usageModels.length > 5
                  text: (root.usageModels.length - 5) + " more"
                  color: root.dimForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Button {
                visible: root.usageFound
                width: parent.width
                leftAlign: true
                text: (root.breakdownOpen ? "▾ " : "▸ ") + "Token breakdown"
                foreground: root.contentForeground
                fontFamily: root.contentFontFamily
                focusable: true
                onClicked: root.breakdownOpen = !root.breakdownOpen
              }

              Column {
                visible: root.breakdownOpen && root.usageFound
                width: parent.width
                spacing: Style.space(4)

                Repeater {
                  model: [
                    { key: "input", label: "Input" },
                    { key: "cacheRead", label: "Cache read" },
                    { key: "cacheWrite", label: "Cache write" },
                    { key: "output", label: "Output" },
                    { key: "reasoning", label: "Reasoning" }
                  ]
                  delegate: Item {
                    id: breakdownRow
                    required property var modelData
                    width: parent.width
                    height: Math.max(breakdownLabel.implicitHeight, breakdownValue.implicitHeight)

                    Text {
                      id: breakdownLabel
                      anchors.left: parent.left
                      anchors.verticalCenter: parent.verticalCenter
                      text: breakdownRow.modelData.label
                      color: root.contentForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.caption
                    }

                    Text {
                      id: breakdownValue
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      text: {
                        var breakdown = root.usageWindow ? root.usageWindow.breakdown : null
                        var value = breakdown ? Number(breakdown[breakdownRow.modelData.key]) : 0
                        return Model.compactNumber(value) + " · " + Model.share(value, root.usageBreakdownTotal)
                      }
                      color: root.contentForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                }
              }

              Text {
                visible: root.usageWindow !== null && root.usageFound
                width: parent.width
                text: Model.usageFooter(root.usageWindowName)
                color: root.dimForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }
        }
      }
    }
  }

  Connections {
    target: keyCatcher.Window.window
    function onActiveFocusItemChanged() {
      var item = keyCatcher.Window.window.activeFocusItem
      if (!root.settingsOpen || !item)
        return
      var ancestor = item
      while (ancestor && ancestor !== settingsContent)
        ancestor = ancestor.parent
      if (!ancestor)
        return
      var position = item.mapToItem(settingsContent, 0, 0).y
      if (position < scroll.contentY)
        scroll.contentY = position
      else if (position + item.height > scroll.contentY + scroll.height)
        scroll.contentY = Math.min(Math.max(0, scroll.contentHeight - scroll.height), position + item.height - scroll.height)
    }
  }
}
