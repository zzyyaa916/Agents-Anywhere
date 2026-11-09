"use client"

import * as React from "react"
import { useAuth } from "@/components/auth/auth-context"
import { apiClient } from "@/lib/api"
import { Button } from "@/components/ui/button"

type UsageWindow = { kind: string; modelScope: string | null; remainingPercent: number; resetsAt: string; windowDurationMins: number }
type Snapshot = { runtime: string; accountKey: string; accountLabel: string; planType: string | null; windows: UsageWindow[]; fetchedAt: string | null; stale: boolean; bindings: { connectorId: string; runtimeId: string }[] }
type Response = { snapshots: Snapshot[]; unavailable: string[] }
type State = { data: Response | null; busy: boolean; refresh: () => Promise<void> }
const Context = React.createContext<State>({ data: null, busy: false, refresh: async () => {} })
export const localTime = (value: string) => new Date(value).toLocaleString(undefined, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
export const windowLabel = (value: UsageWindow) => ({ five_hour: "5 小时", weekly: "周", seven_day: "7 天", weekly_scoped: `周 · ${value.modelScope ?? "模型"}` }[value.kind] ?? `${value.windowDurationMins} 分钟`)

export function AccountUsageProvider({ children }: { children: React.ReactNode }) {
  const { session } = useAuth()
  const token = session?.accessToken
  const [saved, setSaved] = React.useState<{ token: string; data: Response } | null>(null)
  const [busy, setBusy] = React.useState(false)
  const active = React.useRef(token)
  active.current = token
  const read = React.useCallback(async (manual = false) => {
    if (!token) return
    try {
      const data = manual
        ? await apiClient.post<Response>("/account-usage/refresh", {}, { token })
        : await apiClient.get<Response>("/account-usage", { token })
      if (active.current === token) setSaved({ token, data })
    } catch {
      // Retain last values as stale; usage is optional and never blocks the workspace.
      if (active.current === token) setSaved(previous => previous?.token === token ? { token, data: { ...previous.data, snapshots: previous.data.snapshots.map(s => ({ ...s, stale: true })) } } : null)
    }
  }, [token])
  React.useEffect(() => {
    void read()
    const timer = setInterval(() => void read(), 30_000)
    return () => clearInterval(timer)
  }, [read])
  const refresh = React.useCallback(async () => {
    if (busy) return
    setBusy(true)
    try { await read(true) } finally { setBusy(false) }
  }, [busy, read])
  return <Context.Provider value={{ data: saved && saved.token === token ? saved.data : null, busy, refresh }}>{children}</Context.Provider>
}

export function AccountUsagePanel() {
  const { data, busy, refresh } = React.useContext(Context)
  return <section aria-label="账号剩余用量" className="mb-2 max-h-64 overflow-auto rounded-md border p-2 text-xs group-data-[collapsible=icon]:hidden">
    <div className="mb-2 flex items-center justify-between"><span>账号剩余用量</span><Button size="sm" variant="ghost" disabled={busy} onClick={() => void refresh()}>{busy ? "检查中…" : "刷新"}</Button></div>
    {["codex", "claude_code"].map(runtime => {
      const snapshots = data?.snapshots.filter(s => s.runtime === runtime) ?? []
      const name = runtime === "codex" ? "Codex" : "Claude Code"
      return <div key={runtime} className="mb-2 space-y-1">
        {!snapshots.length && <p>{name} · 用量不可用</p>}
        {snapshots.map(s => <div key={s.accountKey} className="space-y-1">
          <p>{name} · {s.accountLabel}{s.planType ? ` · ${s.planType}` : ""}</p>
          {s.windows.map((w, index) => <div key={`${w.kind}-${index}`}>
            <p>{windowLabel(w)} · 剩余 {Math.round(w.remainingPercent)}% · {localTime(w.resetsAt)} 重置</p>
            <progress aria-label={`${name} ${windowLabel(w)}剩余`} value={w.remainingPercent} max={100} className="h-1 w-full accent-primary" />
          </div>)}
          <p className="text-muted-foreground">{s.stale ? "数据已过期 · " : ""}{s.fetchedAt ? `${localTime(s.fetchedAt)} 更新` : "用量不可用"}</p>
        </div>)}
      </div>
    })}
    <p className="text-muted-foreground">刷新受采集间隔限制；Claude 用量接口为非官方接口。</p>
  </section>
}

export function SessionUsageNotice({ connectorId, runtimeId }: { connectorId: string; runtimeId?: string }) {
  const { data } = React.useContext(Context)
  const matches = data?.snapshots.filter(s => s.bindings.some(b => b.connectorId === connectorId && b.runtimeId === runtimeId)) ?? []
  return <>{matches.flatMap(s => s.windows.filter(w => w.kind === "five_hour" && w.remainingPercent <= 20).map((w, index) =>
    <div role="status" key={`${s.accountKey}-${index}`} className={`px-4 py-2 text-sm ${w.remainingPercent === 0 ? "bg-amber-100 text-amber-950 dark:bg-amber-950 dark:text-amber-100" : "bg-muted"}`}>
      {s.runtime === "codex" ? "Codex" : "Claude Code"} 5 小时窗口仅剩 {Math.round(w.remainingPercent)}%，{localTime(w.resetsAt)} 重置{s.stale ? "（数据已过期）" : ""}
    </div>))}</>
}
