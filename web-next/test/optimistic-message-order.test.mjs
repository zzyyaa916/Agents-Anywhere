import assert from "node:assert/strict"
import test from "node:test"
import { registerSource } from "./helpers/onboarding-source.mjs"

const hook = registerSource()
const { buildOptimisticUserMessage, mergeTimelineItems, mergeTimelineSnapshot } = await import("../src/components/session/optimistic-timeline.ts")
hook.deregister()

function item(id, orderSeq, role = "assistant", source = {}) {
  return { id, sessionId: "s", type: "message", status: "done", role,
    content: { text: id }, source, orderSeq, revision: 1, contentHash: id,
    updatedSeq: 1000 + orderSeq, createdAt: "2026-11-12T00:00:00Z",
    updatedAt: "2026-11-12T00:00:00Z", completedAt: null }
}

for (const runtime of ["codex", "claude", "dsh"]) {
  test(`${runtime}: pending user message stays before the streaming reply when event sequence is far ahead`, () => {
    const old = item("old", 10, "assistant", { runtime })
    const pending = buildOptimisticUserMessage({ sessionId: "s", clientMessageId: "sent", text: "question", attachments: [], items: [old], nextSeq: 1000 })
    const reply = item("reply", 12, "assistant", { runtime })
    const streaming = mergeTimelineItems([old, pending], [reply])
    assert.deepEqual(streaming.map(value => value.id), ["old", "optimistic-message:sent", "reply"])
    const echo = item("server-user", 11, "user", { runtime, clientMessageId: "sent" })
    const acknowledged = mergeTimelineItems(streaming, [echo])
    assert.deepEqual(acknowledged.map(value => value.id), ["old", "server-user", "reply"])
    assert.equal(acknowledged.filter(value => value.role === "user").length, 1)
    const snapshot = mergeTimelineSnapshot(streaming, 1012, [old, echo, reply], 1013)
    assert.deepEqual(snapshot.items.map(value => value.id), ["old", "server-user", "reply"])
  })
}

test("multiple pending sends keep their own order and an empty timeline does not use the event cursor", () => {
  const first = buildOptimisticUserMessage({ sessionId: "s", clientMessageId: "one", text: "one", attachments: [], items: [], nextSeq: 1000 })
  const second = buildOptimisticUserMessage({ sessionId: "s", clientMessageId: "two", text: "two", attachments: [], items: [first], nextSeq: 2000 })
  assert.equal(first.orderSeq, 1)
  assert.equal(second.orderSeq, 2)
})
