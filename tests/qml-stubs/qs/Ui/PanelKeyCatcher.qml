import QtQuick

Item {
  property bool blocked: false

  signal closeRequested()
  signal tabRequested(var direction)
  signal activateRequested()
}
