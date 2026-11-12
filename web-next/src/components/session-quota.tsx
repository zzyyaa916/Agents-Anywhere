"use client"

import * as React from "react"
import { apiClient } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { localTime } from "@/components/account-usage"

type Quota = { state: "limited" | "ready" | "stopped" | "resumed"; resetsAt: string | null }
type Response = { quotaLimit: Quota | null }

export function SessionQuotaNotice({ token, sessionId, onReady }: { token: string; sessionId: string; onReady?: () => void }) {
  const [saved, setSaved] = React.useState<{ scope: string; quota: Quota | null } | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [failed, setFailed] = React.useState(false)
  const scope = JSON.stringify([token, sessionId])
  const active = React.useRef(scope)
  active.current = scope
  const notified = React.useRef<string | null>(null)
  const ready = React.useRef(onReady)
  ready.current = onReady
  const read = React.useCallback(async (recheck = false) => {
    try {
      const path = `/sessions/${encodeURIComponent(sessionId)}/quota`
      const response = recheck ? await apiClient.post<Response>(`${path}/recheck`, {}, { token }) : await apiClient.get<Response>(path, { token })
      if (active.current === scope) { setSaved({ scope, quota: response.quotaLimit }); setFailed(false) }
    } catch { if (active.current === scope) setFailed(true) }
  }, [token, sessionId, scope])
  React.useEffect(() => {
    void read()
    const timer = setInterval(() => void read(), 15_000)
    return () => clearInterval(timer)
  }, [read])
  const quota = saved?.scope === scope ? saved.quota : null
  React.useEffect(() => {
    if (!quota || quota.state === "limited") { notified.current = null; return }
    const key = `${scope}:${quota.state}`
    if (notified.current !== key) { notified.current = key; ready.current?.() }
  }, [quota, scope])
  if (!quota || quota.state === "stopped" || quota.state === "resumed") return null
  return <div role="status" className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-amber-400 bg-amber-50 px-4 py-2 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100">
    <span className="min-w-0 break-words">{quota.state === "limited" ? `因限额中断 · 已达用量上限，${quota.resetsAt ? `预计 ${localTime(quota.resetsAt)} 恢复` : "恢复时间未知"}` : "限额等待已结束，可以在原会话继续；若仍受限，将更新恢复时间。"}{failed ? " · 检查失败，请稍后再试" : ""}</span>
    <div className="flex flex-wrap gap-2">
      {quota.state === "limited" && <Button size="sm" variant="outline" disabled={busy} onClick={async () => { setBusy(true); try { await read(true) } finally { setBusy(false) } }}>{busy ? "检查中…" : "重新检查"}</Button>}
      <Button size="sm" variant="outline" disabled={busy} onClick={async () => {
        setBusy(true)
        try {
          const result = await apiClient.post<{ ok: boolean }>(`/sessions/${encodeURIComponent(sessionId)}/runtime/interrupt`, {}, { token })
          if (result.ok) await read()
          else if (active.current === scope) setFailed(true)
        } catch { if (active.current === scope) setFailed(true) } finally { setBusy(false) }
      }}>结束等待</Button>
    </div>
  </div>
}
