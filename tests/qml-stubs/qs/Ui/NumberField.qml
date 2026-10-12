import QtQuick
import qs.Commons

Item {
  id: root

  property string label: ""
  property var value: 0
  property int from: 0
  property int to: 100
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family

  signal modified(var value)

  implicitHeight: 28
}
