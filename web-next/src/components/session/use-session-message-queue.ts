"use client"

import * as React from "react"
import type { AttachedFile } from "@/components/attachment-input"
import { createClientId } from "@/lib/id"

type Item = { id: string; text: string; attachments: AttachedFile[]; status: "queued" | "sending" | "failed" }
type Send = (text: string, attachments: AttachedFile[], options: { clientMessageId?: string; steer?: boolean }) => Promise<boolean>
const active = new Set<string>()

function restore(scope?: string): Item[] {
  if (!scope) return []
  try {
    const value: unknown = JSON.parse(localStorage.getItem(scope) || "[]")
    if (!Array.isArray(value)) return []
    return value.filter(item => item && typeof item.id === "string" && typeof item.text === "string" && Array.isArray(item.attachments)).map(item => ({
      ...item,
      status: item.status === "sending" ? "failed" : item.status === "failed" ? "failed" : "queued",
      attachments: item.attachments.filter((file: AttachedFile) => file.uploaded && typeof file.uploaded.fileId === "string").map((file: AttachedFile) => ({ ...file, file: new File([], file.name, { type: file.mediaType }) })),
    }))
  } catch { return [] }
}

function persist(scope: string | undefined, items: Item[]) {
  if (!scope) return
  if (!items.length) { localStorage.removeItem(scope); return }
  localStorage.setItem(scope, JSON.stringify(items, (key, value) => key === "file" || key === "preview" ? undefined : value))
}

export function useSessionMessageQueue({ scope, canSend, canSteer, autoSend = true, onSend }: { scope?: string; canSend: boolean; canSteer: boolean; autoSend?: boolean; onSend: Send }) {
  const [state, setState] = React.useState(() => { const items = restore(scope); return { scope, items, paused: items.length > 0 } })
  const [error, setError] = React.useState<"storage" | null>(null)
  const latest = React.useRef({ state, scope, canSend, canSteer, onSend })
  latest.current = { state, scope, canSend, canSteer, onSend }
  React.useEffect(() => () => {
    latest.current.state.items.filter(item => item.status === "queued").forEach(item => item.attachments.forEach(file => { if (file.preview) URL.revokeObjectURL(file.preview) }))
  }, [])
  React.useEffect(() => {
    if (state.scope === scope) return
    state.items.filter(item => item.status === "queued").forEach(item => item.attachments.forEach(file => { if (file.preview) URL.revokeObjectURL(file.preview) }))
    const items = restore(scope)
    setState({ scope, items, paused: items.length > 0 })
  }, [scope, state.scope])
  React.useEffect(() => {
    if (!scope) return
    const changed = (event: StorageEvent) => {
      if (event.key === scope) setState({ scope, items: restore(scope), paused: true })
    }
    window.addEventListener("storage", changed)
    return () => window.removeEventListener("storage", changed)
  }, [scope])
  const replace = React.useCallback((items: Item[], paused = latest.current.state.paused) => {
    const current = latest.current
    if (current.state.scope !== current.scope) return false
    try { persist(current.scope, items) } catch { setError("storage"); return false }
    const next = { scope: current.scope, items, paused: items.length > 0 && paused }
    latest.current.state = next
    setState(next)
    setError(null)
    return true
  }, [])
  const enqueue = React.useCallback((text: string, attachments: AttachedFile[]) => replace([...latest.current.state.items, { id: createClientId("msg"), text, attachments, status: "queued" }]), [replace])
  const remove = (id: string) => {
    const item = latest.current.state.items.find(item => item.id === id)
    if (!item || item.status === "sending") return
    if (replace(latest.current.state.items.filter(item => item.id !== id))) item.attachments.forEach(file => { if (file.preview) URL.revokeObjectURL(file.preview) })
  }
  const deliver = async (id: string, steer: boolean) => {
    const original = latest.current
    const lock = original.scope || "aa-message-queue:memory"
    if (active.has(lock) || original.state.items.some(item => item.status === "sending")) return
    active.add(lock)
    const run = async () => {
      const current = latest.current
      if (current.scope !== original.scope || !(steer ? current.canSteer : current.canSend)) return
      const item = current.state.items.find(item => item.id === id)
      if (!item || item.status === "sending") return
      // Other tabs must observe the persisted in-flight marker before sending.
      if (current.scope && restore(current.scope).find(stored => stored.id === id)?.status !== item.status) return
      if (!replace(current.state.items.map(value => value.id === id ? { ...value, status: "sending" } : value))) return
      let sent = false
      try { sent = await current.onSend(item.text, item.attachments, { clientMessageId: id, steer }) } catch { /* Result is uncertain; require manual retry. */ }
      if (latest.current.scope !== original.scope) {
        const stored = restore(original.scope)
        try { persist(original.scope, sent ? stored.filter(value => value.id !== id) : stored.map(value => value.id === id ? { ...value, status: "failed" } : value)) } catch { /* Keep the persisted in-flight record for manual review after restore. */ }
        return
      }
      const items: Item[] = sent ? latest.current.state.items.filter(value => value.id !== id) : latest.current.state.items.map(value => value.id === id ? { ...value, status: "failed" } : value)
      if (!replace(items)) {
        const next = { ...latest.current.state, items }
        latest.current.state = next
        setState(next)
      }
    }
    try {
      if (typeof navigator !== "undefined" && navigator.locks) await navigator.locks.request(lock, run)
      else await run()
    } catch {
      if (latest.current.scope === original.scope) replace(latest.current.state.items.map(item => item.id === id ? { ...item, status: "failed" } : item))
    } finally { active.delete(lock) }
  }
  const items = state.scope === scope ? state.items : []
  React.useEffect(() => {
    const first = items[0]
    if (!state.paused && autoSend && canSend && first?.status === "queued") void deliver(first.id, false)
  }, [items, state.paused, canSend, autoSend])
  const pause = () => {
    const next = { ...latest.current.state, paused: true }
    latest.current.state = next
    setState(next)
  }
  return { items, error, paused: state.paused, enqueue, remove, deliver, pause, resume: () => replace(latest.current.state.items, false) }
}
