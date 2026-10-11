import QtQuick
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
  readonly property var barIdentity: hostWidget || root

  readonly property var rows: hostWidget ? hostWidget.rows : []
  readonly property bool refreshing: hostWidget ? hostWidget.refreshing : false
  readonly property string refreshedAt: hostWidget ? hostWidget.refreshedAt : ""
  readonly property color contentForeground: bar ? bar.barForeground : Color.foreground
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color dimForeground: Qt.darker(contentForeground, 1.5)

  function open() {
    root.nowMs = Date.now()
    if (hostWidget && hostWidget.refreshIfStale) hostWidget.refreshIfStale()
    root.controller.show()
  }

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
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: content
        width: parent.width
        spacing: Style.space(10)

        Item {
          width: parent.width
          height: titleText.implicitHeight

          Text {
            id: titleText
            anchors.left: parent.left
            text: "AI subscription usage"
            color: root.contentForeground
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
          }

          Text {
            anchors.right: parent.right
            anchors.verticalCenter: titleText.verticalCenter
            text: root.refreshing ? "refreshing…" : Model.clockText(root.refreshedAt)
            color: root.dimForeground
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
          }
        }

        PanelSeparator { foreground: root.contentForeground }

        Text {
          visible: root.rows.length === 0
          width: parent.width
          text: root.refreshing ? "Loading…" : "No usage data yet"
          color: root.dimForeground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.body
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
                sourceSize: Qt.size(width * 2, width * 2)
                source: Qt.resolvedUrl("assets/" + Model.logo(card.modelData.provider))
              }

              Text {
                id: nameText
                anchors.left: nameLogo.right
                anchors.leftMargin: Style.space(6)
                text: card.modelData.name
                color: root.contentForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.body
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
                spacing: Style.space(2)

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
                    text: Model.percentText(metric.modelData.percent)
                    color: root.contentForeground
                    font.family: root.contentFontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                Rectangle {
                  width: parent.width
                  height: Style.space(4)
                  radius: height / 2
                  color: Qt.rgba(root.contentForeground.r, root.contentForeground.g, root.contentForeground.b, 0.15)

                  Rectangle {
                    width: parent.width * Math.min(1, Math.max(0, Number(metric.modelData.percent || 0) / 100))
                    height: parent.height
                    radius: parent.radius
                    color: root.contentForeground
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
