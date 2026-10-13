import QtQuick

Item {
  id: root

  property var bar: null
  property string text: ""
  property bool labelVisible: false
  property bool hasVisualContent: false
  property real fixedWidth: -1
  property bool dimmed: false
  property string tooltipText: ""
  property color foreground: "#ffffff"
  property string fontFamily: "sans"
  property real fontSize: 12

  signal pressed(int buttonCode)

  implicitWidth: 24
  implicitHeight: 20
}
