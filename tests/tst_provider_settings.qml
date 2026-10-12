import QtQuick
import QtTest
import "../Model.js" as Model

TestCase {
  name: "ProviderSettings"
  when: windowShown

  Repeater {
    id: entries
    model: [{id: "io.github.nejcm.ai-usage", enabledProviders: ["claude", "codex", "opencode", "cursor"],
      providerOrder: ["cursor", "codex", "claude"], hiddenProviders: ["codex"]}]
    delegate: Item {
      required property var modelData
    }
  }

  function test_restart() {
    var saved = entries.itemAt(0).modelData
    var order = Model.providerOrder(saved.providerOrder)
    compare(order, ["cursor", "codex", "claude", "opencode", "grok", "antigravity", "zai"])
    var enabled = Model.enabledInOrder(order, saved.enabledProviders)
    compare(enabled, ["cursor", "codex", "claude", "opencode"])
    compare(Model.selectedProviders(enabled, saved.hiddenProviders), ["cursor", "claude", "opencode"])
    var toggled = Model.providerList(saved.enabledProviders)
    toggled.splice(toggled.indexOf("codex"), 1)
    compare(toggled, ["claude", "opencode", "cursor"])
    compare(Model.providerList(saved.enabledProviders), ["claude", "codex", "opencode", "cursor"])
  }
}
