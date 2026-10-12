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
  readonly property var barIdentity: hostWidget || root

  readonly property var rows: hostWidget ? hostWidget.displayRows : []
  readonly property bool refreshing: hostWidget ? hostWidget.refreshing : false
  readonly property string refreshedAt: hostWidget ? hostWidget.refreshedAt : ""
  readonly property color contentForeground: bar ? bar.barForeground : Color.foreground
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color dimForeground: Qt.darker(contentForeground, 1.5)

  function open() {
    root.settingsOpen = false
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
              visible: !root.settingsOpen && (root.refreshedAt !== "" || root.refreshing)
              text: root.refreshing ? "refreshing…" : "Updated " + Model.clockText(root.refreshedAt)
              color: root.dimForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Row {
            id: headerActions
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(4)
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
                    source: Qt.resolvedUrl("assets/" + Model.logo(card.modelData.provider, card.modelData.provider === "codex" || card.modelData.provider === "cursor" || card.modelData.provider === "grok" || card.modelData.provider === "zai"))
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
                  visible: Model.statusText(card.modelData) !== ""
                  width: parent.width
                  text: Model.statusText(card.modelData)
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
