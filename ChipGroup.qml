import QtQuick
import qs.Commons
import qs.Ui

// The shell's ButtonGroup is a fixed Row; this keeps its option/cursor API but wraps.
Flow {
  id: root

  property var options: []
  property string value: ""
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property int cursorIndex: -1

  signal changed(string value)

  spacing: Style.spacing.md

  function optionValue(option) {
    return (option && typeof option === "object") ? String(option.value) : String(option)
  }

  function optionLabel(option) {
    return (option && typeof option === "object" && option.label !== undefined) ? String(option.label) : String(option)
  }

  function selectedOptionIndex() {
    for (var i = 0; i < options.length; i++)
      if (optionValue(options[i]) === value) return i
    return -1
  }

  Repeater {
    model: root.options

    delegate: Button {
      required property var modelData
      required property int index
      text: root.optionLabel(modelData)
      selected: root.optionValue(modelData) === root.value
      hasCursor: root.cursorIndex === index
      bordered: true
      foreground: root.foreground
      fontFamily: root.fontFamily
      onClicked: root.changed(root.optionValue(modelData))
    }
  }
}
