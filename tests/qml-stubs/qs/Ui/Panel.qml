import QtQuick

// Test stand-in for the panel base: no controller, no window management.
Item {
  property string moduleName: ""
  property string ipcTarget: ""
  property bool manageIpc: false
  property var bar: null
  property var anchorItem: null
  property var hostWidget: null
  property var settings: ({})
  property bool opened: false
  property bool popoutSwitchClosing: false
  property var controller: QtObject {
    function show() {
    }
    function hide() {
    }
  }

  function open() {
    opened = true
  }

  function close() {
    opened = false
  }

  function toggle() {
    opened = !opened
  }

  function closeForPopoutSwitch() {
    opened = false
  }
}
