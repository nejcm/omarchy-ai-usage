import QtQuick
import qs.Commons

Item {
  id: root

  property bool checked: false
  property bool interactive: false
  property bool cursorRing: false
  property color foreground: Color.foreground
  property real trackHeight: 16

  implicitWidth: trackHeight
  implicitHeight: trackHeight
}
