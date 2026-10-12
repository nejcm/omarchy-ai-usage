import QtQuick
import QtTest

Item {
  id: harness
  width: 400
  height: 800

  QtObject {
    id: host

    property var providerOrder: []
    property var rows: []
    property var enabledProviders: []
    property int refreshMs: 300000
    property string displayMode: "used"
    property int warningThreshold: 80
    property bool colorWarnings: true
    property bool desktopNotifications: false
    property int resetCalls: 0

    function setting(name, fallback) {
      return fallback
    }

    function toggleProviderList() {}
    function moveProvider() {}
    function moveProviderToTop() {}

    function resetSettings() {
      resetCalls += 1
    }
  }

  Loader {
    id: loader
    anchors.fill: parent
  }

  TestCase {
    name: "SettingsReset"
    when: windowShown

    function settings() {
      return loader.item
    }

    function find(rootItem, predicate) {
      if (!rootItem) return null
      if (predicate(rootItem)) return rootItem
      var data = rootItem.data || []
      for (var i = 0; i < data.length; i++) {
        var found = find(data[i], predicate)
        if (found) return found
      }
      return null
    }

    function resetButton() {
      return find(settings(), function(item) { return item.text === "Reset to defaults" })
    }

    function confirmButton() {
      return find(settings(), function(item) { return item.text === "Confirm reset" })
    }

    function resetTimer() {
      return find(settings(), function(item) {
        return typeof item.interval === "number" && typeof item.restart === "function"
      })
    }

    function initTestCase() {
      loader.setSource(Qt.resolvedUrl("../Settings.qml"), { hostWidget: host })
      verify(settings() !== null)
      verify(resetButton() !== null)
      verify(confirmButton() !== null)
      verify(resetTimer() !== null)
    }

    function init() {
      resetTimer().stop()
      resetTimer().interval = 5000
      settings().resetArmed = false
      host.resetCalls = 0
    }

    function test_confirm_disabled_until_armed() {
      compare(confirmButton().enabled, false)
      mouseClick(resetButton())
      compare(settings().resetArmed, true)
      compare(confirmButton().enabled, true)
    }

    function test_tab_reaches_armed_confirm() {
      mouseClick(resetButton())
      waitForRendering(confirmButton())
      resetButton().forceActiveFocus()
      keyClick(Qt.Key_Tab)
      compare(confirmButton().activeFocus, true)
    }

    function test_repeats_while_confirm_focused_do_not_reset() {
      mouseClick(resetButton())
      compare(settings().resetArmed, true)
      waitForRendering(confirmButton())
      confirmButton().forceActiveFocus()
      compare(confirmButton().activeFocus, true)
      var keys = [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space]
      for (var i = 0; i < keys.length; i++) {
        settings().confirmKey({ key: keys[i], isAutoRepeat: true })
        settings().confirmKey({ key: keys[i], isAutoRepeat: true })
      }
      compare(host.resetCalls, 0)
      compare(settings().resetArmed, true)
      settings().confirmKey({ key: Qt.Key_Return, isAutoRepeat: false })
      compare(host.resetCalls, 1)
      compare(settings().resetArmed, false)
    }

    function test_fresh_return_after_tab_confirms() {
      mouseClick(resetButton())
      waitForRendering(confirmButton())
      resetButton().forceActiveFocus()
      keyClick(Qt.Key_Tab)
      compare(confirmButton().activeFocus, true)
      keyClick(Qt.Key_Return)
      compare(host.resetCalls, 1)
      compare(settings().resetArmed, false)
    }

    function test_mouse_confirm_resets() {
      mouseClick(resetButton())
      waitForRendering(confirmButton())
      mouseClick(confirmButton())
      compare(host.resetCalls, 1)
      compare(settings().resetArmed, false)
    }

    function test_expiry_disarms_and_moves_focus() {
      resetTimer().interval = 50
      mouseClick(resetButton())
      compare(settings().resetArmed, true)
      waitForRendering(confirmButton())
      confirmButton().forceActiveFocus()
      compare(confirmButton().activeFocus, true)
      wait(200)
      compare(settings().resetArmed, false)
      compare(confirmButton().activeFocus, false)
      compare(resetButton().activeFocus, true)
      settings().confirmReset()
      compare(host.resetCalls, 0)
      settings().confirmKey({ key: Qt.Key_Return, isAutoRepeat: false })
      compare(host.resetCalls, 0)
    }
  }
}
