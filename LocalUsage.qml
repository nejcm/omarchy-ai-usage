import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root
  required property var hostWidget
  signal openSettingsRequested()
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property bool modelsExpanded: false
  property string usageFilter: ""
  readonly property var usage: hostWidget ? hostWidget.usage : null
  readonly property string usageWindowName: Model.usageWindowName(hostWidget ? hostWidget.setting("usageWindow", Model.SETTING_DEFAULTS.usageWindow) : Model.SETTING_DEFAULTS.usageWindow)
  readonly property var usageWindow: usage && usage.windows ? (usage.windows[usageWindowName] || usage.windows["7d"] || null) : null
  readonly property var usageProviders: usageWindow && usageWindow.providers ? usageWindow.providers : []
  readonly property var usageModels: usageWindow && usageWindow.models ? usageWindow.models : []
  readonly property var usageDays: usageWindow && usageWindow.days ? usageWindow.days : []
  readonly property var usageEnabledToolIds: Model.localUsageProviders(hostWidget ? hostWidget.enabledProviders : [])
  readonly property string usageTool: root.usageEnabledToolIds.indexOf(root.usageFilter) >= 0 ? root.usageFilter : ""
  readonly property var usageFilterOptions: {
    var options = [{ value: "", label: "All" }]
    for (var i = 0; i < root.usageEnabledToolIds.length; i++) {
      var id = root.usageEnabledToolIds[i]
      options.push({ value: id, label: Model.PROVIDER_INFO[id] ? Model.PROVIDER_INFO[id].name : id })
    }
    return options
  }
  readonly property var usageProviderIds: root.usageTool === "" ? Model.providerIds(usageWindow) : [root.usageTool]
  readonly property var usageVisibleProviders: root.usageTool === "" ? usageProviders : usageProviders.filter(function (entry) { return entry.id === root.usageTool })
  readonly property var usageVisibleModels: root.usageTool === "" ? usageModels : usageModels.filter(function (entry) { return entry.provider === root.usageTool })
  readonly property var usageSummary: root.usageTool === "" ? usageWindow : Model.providerSummary(usageWindow, root.usageTool)
  readonly property var usageBreakdown: usageSummary && usageSummary.breakdown ? usageSummary.breakdown : null
  readonly property bool usageScanning: usage !== null && usage.scanning === true
  readonly property bool usageFound: {
    var month = usage && usage.windows ? usage.windows["30d"] : null
    return !!month && Array.isArray(month.providers) && month.providers.length > 0
  }
  readonly property bool usageToolFound: {
    if (root.usageTool === "") return root.usageFound
    return Model.providerSummary(usage && usage.windows ? usage.windows["30d"] : null, root.usageTool) !== null
  }
  readonly property bool usageNoProviders: !!(hostWidget && hostWidget.enabledProviders && hostWidget.enabledProviders.length === 0)
  readonly property bool usageOnboarding: !root.usageNoProviders && usage !== null && !usageScanning && !usageFound
  readonly property bool usageToolEmpty: !root.usageNoProviders && usage !== null && !usageScanning && usageFound && root.usageTool !== "" && !root.usageToolFound
  readonly property string usageMessage: {
    if (root.usageNoProviders) return "No providers enabled"
    if (!usage || usageScanning) return "Scanning local logs…"
    if (root.usageOnboarding) return "No local usage in the last 30 days. Claude Code, Codex, and OpenCode write the logs this tab reads."
    if (root.usageToolEmpty) return (Model.PROVIDER_INFO[root.usageTool] ? Model.PROVIDER_INFO[root.usageTool].name : root.usageTool) + " has no local usage in the last 30 days"
    return ""
  }
  readonly property real usageBreakdownTotal: {
    var breakdown = root.usageBreakdown
    return breakdown ? Number(breakdown.input) + Number(breakdown.cacheRead) + Number(breakdown.cacheWrite) + Number(breakdown.output) + Number(breakdown.reasoning) : 0
  }
  readonly property color dimForeground: Qt.darker(foreground, 1.5)
  spacing: Style.space(20)

  onUsageWindowNameChanged: root.modelsExpanded = false
  onUsageFilterChanged: root.modelsExpanded = false
  onUsageEnabledToolIdsChanged: if (root.usageFilter !== "" && root.usageEnabledToolIds.indexOf(root.usageFilter) < 0) root.usageFilter = ""

  component SectionLabel: Text {
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
    textFormat: Text.PlainText
  }

  component StatCell: Column {
    id: cell
    required property string label
    required property string value
    spacing: Style.space(2)

    Text {
      text: cell.value
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    Text {
      text: cell.label
      color: root.dimForeground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  ButtonGroup {
    width: parent.width
    options: [
      { value: "today", label: "Today" },
      { value: "7d", label: "7D" },
      { value: "30d", label: "30D" }
    ]
    value: root.usageWindowName
    foreground: root.foreground
    fontFamily: root.fontFamily
    onChanged: function (value) {
      if (root.hostWidget) root.hostWidget.saveSetting("usageWindow", value)
    }
  }

  ButtonGroup {
    visible: root.usageFilterOptions.length > 1
    width: parent.width
    options: root.usageFilterOptions
    value: root.usageTool
    foreground: root.foreground
    fontFamily: root.fontFamily
    onChanged: function (value) {
      root.usageFilter = value
    }
  }

  Text {
    visible: root.usageMessage !== ""
    width: parent.width
    text: root.usageMessage
    color: root.dimForeground
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    wrapMode: Text.WordWrap
  }

  Button {
    visible: root.usageOnboarding
    text: "Open settings"
    foreground: root.foreground
    fontFamily: root.fontFamily
    focusable: true
    onClicked: root.openSettingsRequested()
  }

  Button {
    visible: root.usageToolEmpty
    text: "Show all"
    foreground: root.foreground
    fontFamily: root.fontFamily
    focusable: true
    onClicked: root.usageFilter = ""
  }

  Row {
    visible: root.usageWindow !== null && root.usageToolFound
    spacing: Style.space(16)

    StatCell { label: "tokens"; value: Model.compactNumber(root.usageSummary ? root.usageSummary.tokens : 0) }
    StatCell { label: "output"; value: Model.compactNumber(root.usageSummary ? root.usageSummary.output : 0) }
    StatCell { label: "sessions"; value: String(root.usageSummary ? root.usageSummary.sessions : 0) }
    StatCell { label: "cache hit"; value: Model.percentText(100 * Number(root.usageSummary ? root.usageSummary.cacheHit : 0)) }
  }

  Column {
    visible: root.usageDays.length > 0 && root.usageToolFound
    width: parent.width
    spacing: Style.space(2)

    Item {
      id: dayChart
      width: parent.width
      height: Style.space(64)

      Row {
        id: dayBars
        anchors.fill: parent
        spacing: Style.space(2)
        readonly property real max: Model.dayMax(root.usageDays, root.usageProviderIds)

        Repeater {
          model: root.usageDays
          delegate: Item {
            id: dayBar
            required property var modelData
            width: (dayBars.width - dayBars.spacing * (root.usageDays.length - 1)) / root.usageDays.length
            height: dayBars.height

            Repeater {
              model: root.usageProviderIds
              delegate: Rectangle {
                required property string modelData
                required property int index
                readonly property real tokens: Model.dayProviderTokens(dayBar.modelData, modelData)
                width: dayBar.width
                height: tokens / Math.max(1, dayBars.max) * dayBar.height
                y: dayBar.height - (Model.stackOffset(dayBar.modelData, root.usageProviderIds, index) / Math.max(1, dayBars.max) * dayBar.height) - height
                visible: tokens > 0
                color: Model.providerColor(modelData)
              }
            }
          }
        }
      }
    }

    Item {
      width: parent.width
      height: dayAxisLeft.implicitHeight

      Text {
        id: dayAxisLeft
        anchors.left: parent.left
        text: root.usageDays.length > 0 ? Model.dayLabel(root.usageDays[0].date) : ""
        color: root.dimForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.usageDays.length > 0 ? Model.dayLabel(root.usageDays[Math.floor(root.usageDays.length / 2)].date) : ""
        color: root.dimForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Text {
        anchors.right: parent.right
        text: "now"
        color: root.dimForeground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }

  Column {
    visible: root.usageVisibleProviders.length > 0
    width: parent.width
    spacing: Style.space(6)

    SectionLabel { text: "Tokens by tool" }

    Repeater {
      model: root.usageVisibleProviders
      delegate: Item {
        id: toolRow
        required property var modelData
        width: parent.width
        height: Math.max(toolName.implicitHeight, toolValue.implicitHeight)

        Rectangle {
          id: toolDot
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(8)
          height: width
          radius: width / 2
          color: Model.providerColor(toolRow.modelData.id)
        }

        Text {
          id: toolName
          anchors.left: toolDot.right
          anchors.leftMargin: Style.space(8)
          anchors.right: toolTrack.left
          anchors.rightMargin: Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          text: Model.PROVIDER_INFO[toolRow.modelData.id] ? Model.PROVIDER_INFO[toolRow.modelData.id].name : toolRow.modelData.id
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          id: toolValue
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width * 0.2
          horizontalAlignment: Text.AlignRight
          text: Model.compactNumber(toolRow.modelData.tokens)
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Rectangle {
          id: toolTrack
          anchors.right: toolValue.left
          anchors.rightMargin: Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width * 0.3
          height: Style.space(4)
          radius: height / 2
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)

          Rectangle {
            width: toolRow.modelData.tokens / Math.max(1, root.usageVisibleProviders[0].tokens) * parent.width
            height: parent.height
            radius: parent.radius
            color: Model.providerColor(toolRow.modelData.id)
          }
        }
      }
    }
  }

  Column {
    visible: root.usageVisibleModels.length > 0
    width: parent.width
    spacing: Style.space(6)

    SectionLabel { text: "Tokens by model" }

    Repeater {
      model: root.usageVisibleModels
      delegate: Column {
        id: modelRow
        required property var modelData
        required property int index
        width: parent.width
        spacing: Style.space(2)
        visible: root.modelsExpanded || index < 5

        Item {
          width: parent.width
          height: modelName.implicitHeight

          Rectangle {
            id: modelDot
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(8)
            height: width
            radius: width / 2
            color: Model.providerColor(modelRow.modelData.provider)
          }

          Rectangle {
            id: modelTrack
            anchors.right: modelValue.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width * 0.3
            height: Style.space(4)
            radius: height / 2
            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)

            Rectangle {
              width: modelRow.modelData.tokens / Math.max(1, root.usageVisibleModels[0].tokens) * parent.width
              height: parent.height
              radius: parent.radius
              color: Model.providerColor(modelRow.modelData.provider)
            }
          }

          Text {
            id: modelName
            anchors.left: modelDot.right
            anchors.leftMargin: Style.space(8)
            anchors.right: modelTrack.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            text: modelRow.modelData.name
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            id: modelValue
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width * 0.2
            horizontalAlignment: Text.AlignRight
            text: Model.compactNumber(modelRow.modelData.tokens)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Text {
          anchors.left: parent.left
          anchors.leftMargin: Style.space(16)
          anchors.right: parent.right
          text: Model.PROVIDER_INFO[modelRow.modelData.provider] ? Model.PROVIDER_INFO[modelRow.modelData.provider].name : modelRow.modelData.provider
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: root.dimForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    Button {
      visible: root.usageVisibleModels.length > 5
      text: root.modelsExpanded ? "Show less" : (root.usageVisibleModels.length - 5) + " more"
      foreground: root.foreground
      fontFamily: root.fontFamily
      focusable: true
      onClicked: root.modelsExpanded = !root.modelsExpanded
    }
  }

  Column {
    visible: root.usageToolFound
    width: parent.width
    spacing: Style.space(6)

    SectionLabel { text: "Token breakdown" }

    Repeater {
      model: [
        { key: "input", label: "Input" },
        { key: "cacheRead", label: "Cache read" },
        { key: "cacheWrite", label: "Cache write" },
        { key: "output", label: "Output" },
        { key: "reasoning", label: "Reasoning" }
      ]
      delegate: Item {
        id: breakdownRow
        required property var modelData
        width: parent.width
        height: Math.max(breakdownLabel.implicitHeight, breakdownValue.implicitHeight)

        Text {
          id: breakdownLabel
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          text: breakdownRow.modelData.label
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          id: breakdownValue
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          text: {
            var breakdown = root.usageBreakdown
            var value = breakdown ? Number(breakdown[breakdownRow.modelData.key]) : 0
            return Model.compactNumber(value) + " · " + Model.share(value, root.usageBreakdownTotal)
          }
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  Text {
    visible: root.usageWindow !== null && root.usageToolFound
    width: parent.width
    text: Model.usageFooter(root.usageWindowName)
    color: root.dimForeground
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }
}
