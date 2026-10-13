import QtQuick

// Test stand-in for the keyboard panel host: fixed sizing, no window.
Item {
  property var anchorItem: null
  property var owner: null
  property var bar: null
  property bool open: false
  property var focusTarget: null
  property real contentWidth: 0
  property real contentHeight: 0
  property real screenH: 1000

  function fittedContentWidth(preferred) {
    return preferred
  }

  function fittedContentHeight(preferred, maximum) {
    return Math.min(preferred, maximum)
  }
}
