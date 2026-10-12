pragma Singleton
import QtQuick

QtObject {
  readonly property TextStyle font: TextStyle {}

  function space(value) {
    return value
  }
}
