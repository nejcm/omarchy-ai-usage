import QtQuick
import qs.Commons

// Test stand-in for qs.Ui.Button: same focus and activation semantics as the host.
Item {
  id: root

  property string text: ""
  property string iconText: ""
  property string tooltipText: ""
  property bool selected: false
  property bool bordered: false
  property bool focusable: false
  property bool leftAlign: false
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body
  property real horizontalPadding: 8
  property real verticalPadding: 4

  signal clicked()

  implicitWidth: Math.max(24, text.length * 7 + horizontalPadding * 2)
  implicitHeight: fontSize + verticalPadding * 2 + 8
  activeFocusOnTab: focusable

  Keys.onReturnPressed: if (focusable) root.clicked()
  Keys.onEnterPressed: if (focusable) root.clicked()
  Keys.onSpacePressed: if (focusable) root.clicked()

  MouseArea {
    anchors.fill: parent
    onClicked: {
      if (root.focusable) root.forceActiveFocus()
      root.clicked()
    }
  }
}
