import QtQuick

// Test stand-in for the plugin bar widget base: settings lookup only.
Item {
  property string moduleName: ""
  property var settings: ({})
  property var bar: null
  property real scaledHorizontalMargin: 4

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }
}
