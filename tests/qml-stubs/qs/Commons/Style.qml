pragma Singleton
import QtQuick

QtObject {
  readonly property TextStyle font: TextStyle {}
  readonly property QtObject spacing: QtObject {
    readonly property real sm: 4
  }

  function space(value) {
    return value
  }
}
