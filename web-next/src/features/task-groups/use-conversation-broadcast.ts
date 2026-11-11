"use client"

import * as React from "react"
import { readConversationState, writeConversationState } from "./conversation-storage"

export function useConversationBroadcast(scope: string, sessionIds: string[]) {
  const stored = React.useMemo(() => readConversationState(scope), [scope])
  const [draft, updateDraft] = React.useState(typeof stored.draft === "string" ? stored.draft : "")
  const delivered = React.useRef(new Set(Array.isArray(stored.delivered) ? stored.delivered.filter((id): id is string => typeof id === "string") : []))
  const [sending, setSending] = React.useState(false)
  const inFlight = React.useRef(false)
  const [error, setError] = React.useState("")
  const queues = React.useRef(new Map<string, (text: string) => boolean>())
  const callbacks = React.useRef(new Map<string, (enqueue: ((text: string) => boolean) | null) => void>())
  const [, setQueueRevision] = React.useState(0)
  const signature = sessionIds.join(",")
  React.useEffect(() => {
    const saved = readConversationState(scope)
    updateDraft(typeof saved.draft === "string" ? saved.draft : "")
    delivered.current = new Set(Array.isArray(saved.delivered) ? saved.delivered.filter((id): id is string => typeof id === "string") : [])
    setError("")
  }, [scope, signature])
  const save = (content: string) => {
    if (!writeConversationState(scope, { draft: content, delivered: [...delivered.current] })) setError("无法保存联立输入状态，请保持当前页面打开。")
  }
  const setDraft = (content: string) => { delivered.current.clear(); updateDraft(content); save(content) }
  const registerQueue = (id: string) => {
    if (!callbacks.current.has(id)) callbacks.current.set(id, enqueue => {
      if (enqueue) queues.current.set(id, enqueue)
      else queues.current.delete(id)
      setQueueRevision(value => value + 1)
    })
    return callbacks.current.get(id)!
  }
  const ready = sessionIds.length > 0 && sessionIds.every(id => queues.current.has(id))
  const send = async () => {
    if (inFlight.current || !ready || !draft.trim()) return
    inFlight.current = true; setSending(true); setError("")
    try {
      for (const id of sessionIds) {
        if (delivered.current.has(id)) continue
        if (!queues.current.get(id)?.(draft)) throw new Error("部分会话未能接收，请检查其连接与权限后重试；已接收的会话不会重复发送。")
        delivered.current.add(id); save(draft)
      }
      delivered.current.clear(); updateDraft(""); save("")
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { inFlight.current = false; setSending(false) }
  }
  return { draft, setDraft, sending, error, registerQueue, ready, send }
}
