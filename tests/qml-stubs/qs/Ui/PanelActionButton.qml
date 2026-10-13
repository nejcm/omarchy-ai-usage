import QtQuick
import qs.Commons

Item {
  id: root

  property string iconText: ""
  property string tooltipText: ""
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property bool focusable: false
  property bool hasCursor: false
  property real fontSize: Style.font.body
  property real size: 22

  signal clicked()

  implicitWidth: 22
  implicitHeight: 22
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
