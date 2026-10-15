import QtQuick
import qs.Commons

Item {
  id: root

  property var options: []
  property var value: undefined
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property bool focusable: true
  property int cursorIndex: -1

  signal changed(var value)

  implicitHeight: 24
  activeFocusOnTab: focusable

  function optionValue(option) {
    return (option && typeof option === "object") ? String(option.value) : String(option)
  }

  function selectedOptionIndex() {
    for (var i = 0; i < options.length; i++)
      if (optionValue(options[i]) === value) return i
    return -1
  }
}
