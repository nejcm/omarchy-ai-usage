import QtQuick
import qs.Commons

Item {
  id: root

  property string label: ""
  property string description: ""
  property bool checked: false
  property real titleSize: Style.font.body
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family

  signal clicked()

  implicitHeight: 32
}
