import QtQuick
import qs.Commons

Item {
  id: root

  property var options: []
  property var value: undefined
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family

  signal changed(var value)

  implicitHeight: 24
}
