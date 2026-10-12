import QtQuick
import QtTest
import "../Model.js" as Model

TestCase {
  name: "ProviderSettings"
  when: windowShown

  Repeater {
    id: entries
    model: [{id: "io.github.nejcm.ai-usage", enabledProviders: ["claude", "codex", "opencode", "cursor"],
      providerOrder: ["cursor", "codex", "claude"], hiddenProviders: ["codex"],
      warningState: {"claude:Session": {period: "t", fired: true}}}]
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

  function test_reset_settings_to_defaults() {
    var saved = entries.itemAt(0).modelData
    var reset = Model.resetSettings(saved)
    compare(Model.providerOrder(reset.providerOrder), Model.PROVIDERS)
    compare(Model.enabledInOrder(Model.providerOrder(reset.providerOrder), reset.enabledProviders), Model.DEFAULT_ENABLED)
    compare(Model.selectedProviders(reset.enabledProviders, reset.hiddenProviders), Model.DEFAULT_ENABLED)
    compare(reset.refreshIntervalSec, 300)
    compare(reset.displayMode, "used")
    compare(reset.warningThreshold, 80)
    compare(reset.colorWarnings, true)
    compare(reset.desktopNotifications, false)
    compare(reset.warningState["claude:Session"].fired, true)
    compare(saved.providerOrder, ["cursor", "codex", "claude"])
  }

  function test_move_to_top() {
    var saved = entries.itemAt(0).modelData
    compare(Model.moveItem(saved.providerOrder, "claude", 0), ["claude", "cursor", "codex"])
    compare(saved.providerOrder, ["cursor", "codex", "claude"])
    var order = Model.providerOrder(saved.providerOrder)
    compare(Model.moveItem(order, "zai", 0), ["zai", "cursor", "codex", "claude", "opencode", "grok", "antigravity"])
    compare(Model.moveItem(order, "cursor", -1), order)
    compare(Model.moveItem(order, "grok", 99), ["cursor", "codex", "claude", "opencode", "antigravity", "zai", "grok"])
    compare(Model.moveItem(order, "missing", 0), order)
  }

  function test_elapsed_fraction() {
    var now = Date.parse("2026-10-13T00:00:00Z")
    compare(Model.elapsedFraction({ windowMinutes: 7 * 24 * 60, resetsAt: "2026-10-14T00:00:00Z" }, now), 6 / 7)
    compare(Model.elapsedFraction({ windowMinutes: 24 * 60, resetsAt: "2026-10-13T12:00:00Z" }, now), 0.5)
    compare(Model.elapsedFraction({ windowMinutes: null, resetsAt: "2026-10-14T00:00:00Z" }, now), -1)
    compare(Model.elapsedFraction({ windowMinutes: 300, resetsAt: "" }, now), -1)
    compare(Model.elapsedFraction({ windowMinutes: 300, resetsAt: "2026-10-12T00:00:00Z" }, now), -1)
  }
}
