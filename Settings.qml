import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root
  required property var hostWidget
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property bool resetArmed: false
  spacing: Style.space(12)

  function armReset() {
    if (root.resetArmed) return
    root.resetArmed = true
    resetTimer.restart()
  }

  function confirmReset() {
    resetTimer.stop()
    root.resetArmed = false
    root.hostWidget.resetSettings()
    resetButton.forceActiveFocus()
  }

  component Label: Text {
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    textFormat: Text.PlainText
  }

  component ProviderToggle: Button {
    property bool checked: false
    width: parent.width
    foreground: root.foreground
    fontFamily: root.fontFamily
    horizontalPadding: Style.space(8)
    verticalPadding: Style.space(5)
    leftAlign: true
    bordered: true
    focusable: true

    ToggleSwitch {
      anchors.right: parent.right
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      checked: parent.checked
      foreground: root.foreground
      trackHeight: Style.space(16)
      cursorRing: false
      interactive: false
    }
  }

  Label {
    text: "Providers"
    font.bold: true
  }

  Repeater {
    model: root.hostWidget.providerOrder
    delegate: Column {
      id: provider
      required property string modelData
      required property int index
      readonly property var usageRow: {
        var rows = root.hostWidget.rows || []
        for (var i = 0; i < rows.length; i++) {
          if (rows[i].provider === provider.modelData) return rows[i]
        }
        return null
      }
      width: root.width
      spacing: Style.space(4)

      Row {
        width: parent.width
        spacing: Style.space(4)
        Label {
          width: parent.width - toTop.implicitWidth - up.implicitWidth - down.implicitWidth - parent.spacing * 3
          text: Model.PROVIDER_INFO[provider.modelData].name
          anchors.verticalCenter: parent.verticalCenter
          font.bold: true
        }
        PanelActionButton {
          id: toTop
          iconText: "⇑"
          tooltipText: "Move " + Model.PROVIDER_INFO[provider.modelData].name + " to top"
          foreground: root.foreground
          focusable: true
          enabled: provider.index > 0
          onClicked: root.hostWidget.moveProviderToTop(provider.modelData)
        }
        PanelActionButton {
          id: up
          iconText: "↑"
          tooltipText: "Move " + Model.PROVIDER_INFO[provider.modelData].name + " up"
          foreground: root.foreground
          focusable: true
          enabled: provider.index > 0
          onClicked: root.hostWidget.moveProvider(provider.modelData, -1)
        }
        PanelActionButton {
          id: down
          iconText: "↓"
          tooltipText: "Move " + Model.PROVIDER_INFO[provider.modelData].name + " down"
          foreground: root.foreground
          focusable: true
          enabled: provider.index < root.hostWidget.providerOrder.length - 1
          onClicked: root.hostWidget.moveProvider(provider.modelData, 1)
        }
      }
      Text {
        visible: Model.connectHint(provider.usageRow) !== ""
        width: parent.width
        text: Model.connectHint(provider.usageRow)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
      ProviderToggle {
        text: "Enabled"
        checked: root.hostWidget.enabledProviders.indexOf(provider.modelData) >= 0
        onClicked: root.hostWidget.toggleProviderList("enabledProviders", provider.modelData, root.hostWidget.setting("enabledProviders", Model.SETTING_DEFAULTS.enabledProviders))
      }
      ProviderToggle {
        text: "Show in navbar"
        enabled: root.hostWidget.enabledProviders.indexOf(provider.modelData) >= 0
        opacity: enabled ? 1 : 0.45
        checked: root.hostWidget.setting("hiddenProviders", Model.SETTING_DEFAULTS.hiddenProviders).indexOf(provider.modelData) < 0
        onClicked: root.hostWidget.toggleProviderList("hiddenProviders", provider.modelData, root.hostWidget.setting("hiddenProviders", Model.SETTING_DEFAULTS.hiddenProviders))
      }
    }
  }

  PanelSeparator {
    foreground: root.foreground
  }
  Label {
    text: "Refresh interval"
    font.bold: true
  }
  Flow {
    width: parent.width
    spacing: Style.space(4)
    Repeater {
      model: Model.REFRESH_MINUTES
      delegate: Button {
        required property int modelData
        text: modelData + "m"
        foreground: root.foreground
        fontFamily: root.fontFamily
        focusable: true
        selected: root.hostWidget.refreshMs === modelData * 60000
        onClicked: root.hostWidget.saveSetting("refreshIntervalSec", modelData * 60)
      }
    }
  }

  Label {
    text: "Navbar display"
    font.bold: true
  }
  ButtonGroup {
    options: [
      {
        value: "used",
        label: "Used"
      },
      {
        value: "remaining",
        label: "Remaining"
      },
      {
        value: "both",
        label: "Both"
      }
    ]
    value: root.hostWidget.displayMode
    foreground: root.foreground
    fontFamily: root.fontFamily
    onChanged: function (value) {
      root.hostWidget.saveSetting("displayMode", value)
    }
  }
  Label {
    width: parent.width
    text: "Percentages use the most-used limit. Both shows used / remaining."
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  PanelSeparator {
    foreground: root.foreground
  }
  Label {
    text: "Warnings"
    font.bold: true
  }
  NumberField {
    label: "Warn at usage (%)"
    value: root.hostWidget.warningThreshold
    from: 1
    to: 100
    foreground: root.foreground
    fontFamily: root.fontFamily
    onModified: function (value) {
      root.hostWidget.saveSetting("warningThreshold", value)
    }
  }
  Toggle {
    width: parent.width
    label: "Warning colors"
    titleSize: Style.font.body
    description: "Highlight limits at or above the threshold."
    checked: root.hostWidget.colorWarnings
    foreground: root.foreground
    fontFamily: root.fontFamily
    onClicked: root.hostWidget.saveSetting("colorWarnings", !checked)
  }
  Toggle {
    width: parent.width
    label: "Desktop notifications"
    titleSize: Style.font.body
    description: "Once per limit period, including providers hidden from the navbar."
    checked: root.hostWidget.desktopNotifications
    foreground: root.foreground
    fontFamily: root.fontFamily
    onClicked: root.hostWidget.saveSetting("desktopNotifications", !checked)
  }

  Button {
    visible: root.hostWidget && Model.anyNeedsSignIn(root.hostWidget.rows)
    text: "Troubleshooting"
    iconText: "↗"
    tooltipText: Model.TROUBLESHOOTING_URL
    foreground: root.foreground
    fontFamily: root.fontFamily
    focusable: true
    onClicked: Qt.openUrlExternally(Model.TROUBLESHOOTING_URL)
  }

  PanelSeparator {
    foreground: root.foreground
  }
  Button {
    id: resetButton
    width: parent.width
    leftAlign: true
    text: "Reset to defaults"
    tooltipText: "Restore provider enablement, order, and preferences"
    foreground: root.foreground
    fontFamily: root.fontFamily
    focusable: true
    onClicked: root.armReset()
  }
  Button {
    visible: root.resetArmed
    width: parent.width
    leftAlign: true
    text: "Confirm reset"
    tooltipText: "Restore all settings to their defaults"
    selected: true
    foreground: Color.urgent
    fontFamily: root.fontFamily
    focusable: true
    onClicked: root.confirmReset()
  }
  Timer {
    id: resetTimer
    interval: 5000
    onTriggered: root.resetArmed = false
  }
}
