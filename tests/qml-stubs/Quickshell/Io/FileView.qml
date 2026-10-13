import QtQuick

QtObject {
  property string path: ""
  property bool atomicWrites: false
  property bool printErrors: false

  signal loaded()
  signal loadFailed()

  function text() {
    return ""
  }

  function setText(value) {
  }
}
