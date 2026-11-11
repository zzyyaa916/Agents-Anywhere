import assert from "node:assert/strict"
import test from "node:test"
import { registerSource } from "./helpers/onboarding-source.mjs"
const hook = registerSource()
const { parseForwardCommand } = await import("../src/features/task-groups/forward-command.ts")
const { catalogI18nText } = await import("../src/components/session/catalog-selection.ts")
hook.deregister()
test("explicit Chinese forwarding preserves instructions and ignores ordinary discussion", () => {
  assert.deepEqual(parseForwardCommand("转发给 Codex：请审核当前代码\n不要修改文件"), {targets:["Codex"], instructions:"请审核当前代码\n不要修改文件"})
  assert.equal(parseForwardCommand("解释一下如何转发给Claude"), null)
  assert.equal(parseForwardCommand("转发给"), null)
  assert.deepEqual(parseForwardCommand("转发给 Codex、Unknown AI：审核").targets, ["Codex", "Unknown AI"])
  assert.deepEqual(parseForwardCommand("转发给 Codex、Unknown").targets, ["Codex", "Unknown"])
  assert.equal(parseForwardCommand("转发给Claude").targets[0], "Claude")
  assert.deepEqual(parseForwardCommand("转发给 Claude Code：继续执行"), {targets:["Claude Code"],instructions:"继续执行"})
  assert.deepEqual(parseForwardCommand("转发给 我的 Codex：审核", ["我的 Codex"]), {targets:["我的 Codex"],instructions:"审核"})
})

test("known reasoning levels use localized labels while catalog metadata retains priority", () => {
  assert.equal(catalogI18nText(key => ({"reasoningModes.high":"高"})[key], {}, "labelKey", "High", "high"), "高")
  assert.equal(catalogI18nText(key => key, {i18n:{labelKey:"custom"}}, "labelKey", "High", "high"), "custom")
  assert.equal(catalogI18nText(key => key, {}, "labelKey", "Vendor effort", "unknown"), "Vendor effort")
})


test("a source-independent command names two recipients and preserves the entire instruction", () => {
  for (const targets of [["Claude Code", "DSH"], ["Codex", "DSH"], ["Codex", "Claude Code"]]) {
    assert.deepEqual(parseForwardCommand(`转发给 ${targets.join("、")}：请审核\n保留附件`), { targets, instructions: "请审核\n保留附件" })
  }
  assert.deepEqual(parseForwardCommand("转发给 Codex, DSH：审核"), { targets: ["Codex", "DSH"], instructions: "审核" })
})
