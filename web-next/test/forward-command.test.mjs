import assert from "node:assert/strict"
import test from "node:test"
import { registerSource } from "./helpers/onboarding-source.mjs"
const hook = registerSource()
const { parseForwardCommand } = await import("../src/features/task-groups/forward-command.ts")
hook.deregister()
test("explicit Chinese forwarding preserves instructions and ignores ordinary discussion", () => {
  assert.deepEqual(parseForwardCommand("转发给 Codex：请审核当前代码\n不要修改文件"), {target:"Codex", instructions:"请审核当前代码\n不要修改文件"})
  assert.equal(parseForwardCommand("解释一下如何转发给Claude"), null)
  assert.equal(parseForwardCommand("转发给"), null)
  assert.equal(parseForwardCommand("转发给Claude").target, "Claude")
  assert.deepEqual(parseForwardCommand("转发给 Claude Code：继续执行"), {target:"Claude Code",instructions:"继续执行"})
  assert.deepEqual(parseForwardCommand("转发给 我的 Codex：审核", ["我的 Codex"]), {target:"我的 Codex",instructions:"审核"})
})
