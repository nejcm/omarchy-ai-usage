import QtQuick

// Test stand-in for Quickshell's Process: tracks state without spawning anything.
Item {
  id: root

  property var command: []
  property bool running: false
  property var stdout: null
  property int starts: 0

  signal exited(int exitCode, int exitStatus)

  onRunningChanged: if (running) starts += 1

  function emitStream(text) {
    if (stdout) stdout.streamFinished(text)
  }
}
