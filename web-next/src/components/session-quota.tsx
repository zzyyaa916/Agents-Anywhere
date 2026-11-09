"use client"

import * as React from "react"
import { apiClient } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { localTime } from "@/components/account-usage"

type Quota = { state: "limited" | "ready" | "stopped" | "resumed"; resetsAt: string | null }
type Response = { quotaLimit: Quota | null }

export function SessionQuotaNotice({ token, sessionId }: { token: string; sessionId: string }) {
  const [saved, setSaved] = React.useState<{ sessionId: string; quota: Quota | null } | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [failed, setFailed] = React.useState(false)
  const active = React.useRef(sessionId)
  active.current = sessionId
  const read = React.useCallback(async (recheck = false) => {
    try {
      const path = `/sessions/${encodeURIComponent(sessionId)}/quota`
      const response = recheck ? await apiClient.post<Response>(`${path}/recheck`, {}, { token }) : await apiClient.get<Response>(path, { token })
      if (active.current === sessionId) { setSaved({ sessionId, quota: response.quotaLimit }); setFailed(false) }
    } catch { if (active.current === sessionId) setFailed(true) }
  }, [token, sessionId])
  React.useEffect(() => {
    void read()
    const timer = setInterval(() => void read(), 15_000)
    return () => clearInterval(timer)
  }, [read])
  const quota = saved?.sessionId === sessionId ? saved.quota : null
  if (!quota || quota.state === "stopped" || quota.state === "resumed") return null
  return <div role="status" className="flex items-center justify-between gap-2 border-b border-amber-400 bg-amber-50 px-4 py-2 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100">
    <span>{quota.state === "limited" ? `因限额中断 · 已达用量上限，${quota.resetsAt ? `预计 ${localTime(quota.resetsAt)} 恢复` : "恢复时间未知"}` : "限额等待已结束，可以在原会话继续；若仍受限，将更新恢复时间。"}{failed ? " · 检查失败，请稍后再试" : ""}</span>
    {quota.state === "limited" && <Button size="sm" variant="outline" disabled={busy} onClick={async () => { setBusy(true); try { await read(true) } finally { setBusy(false) } }}>{busy ? "检查中…" : "重新检查"}</Button>}
  </div>
}
