"use client"

import * as React from "react"
import { Gauge } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useAuth } from "@/components/auth/auth-context"
import { apiClient } from "@/lib/api"
import { Button } from "@/components/ui/button"

type UsageWindow = { kind: string; modelScope: string | null; usedPercent?: number; remainingPercent: number; resetsAt: string; windowDurationMins: number; source?: "event" | "probe" | null; receivedAt?: string | null; ageSeconds?: number | null }
type Snapshot = { runtime: string; accountKey: string; accountLabel: string; planType: string | null; windows: UsageWindow[]; fetchedAt: string | null; stale: boolean; errorCode?: string | null; bindings: { connectorId: string; runtimeId: string }[] }
type Refresh = { status: "idle" | "running" | "success" | "retry" | "offline" | "circuit" | "disabled"; nextAllowedAt?: string | null; completedAt?: string | null; errorCode?: string | null }
type Response = { snapshots: Snapshot[]; unavailable: string[]; serverTime?: string; refresh?: Refresh }
type State = { data: Response | null; busy: boolean; failed: boolean; elapsed: number; read: () => Promise<void>; refresh: () => Promise<void> }
const Context = React.createContext<State>({ data: null, busy: false, failed: false, elapsed: 0, read: async () => {}, refresh: async () => {} })
export const useAccountUsage = () => React.useContext(Context)
export const localTime = (value: string) => new Date(value).toLocaleString(undefined, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
export const windowLabel = (value: UsageWindow) => ({ five_hour: "5 小时", weekly: "周", seven_day: "7 天", weekly_scoped: `周 · ${value.modelScope ?? "模型"}` }[value.kind] ?? `${value.windowDurationMins} 分钟`)
export function usageAge(seconds: number | null | undefined): string {
  if (seconds == null) return "接收时间未知"
  if (seconds < 60) return "刚刚"
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

export function AccountUsageProvider({ children }: { children: React.ReactNode }) {
  const { session } = useAuth()
  const token = session?.accessToken
  const [saved, setSaved] = React.useState<{ token: string; data: Response; at: number } | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [failed, setFailed] = React.useState(false)
  const [tick, setTick] = React.useState(() => performance.now())
  const active = React.useRef(token)
  const sending = React.useRef(false)
  const readRevision = React.useRef(0)
  active.current = token
  const read = React.useCallback(async (manual = false) => {
    if (!token) return
    const revision = ++readRevision.current
    try {
      const data = manual ? await apiClient.post<Response>("/account-usage/refresh", {}, { token }) : await apiClient.get<Response>("/account-usage", { token })
      if (active.current === token && readRevision.current === revision) {
        const at = performance.now()
        setSaved({ token, data, at }); setTick(at); setFailed(false)
      }
    } catch {
      // Transport failures affect only the refresh control, never the cached values or their age.
      if (active.current === token && readRevision.current === revision) setFailed(true)
    }
  }, [token])
  React.useEffect(() => { void read() }, [read])
  React.useEffect(() => {
    const timer = setInterval(() => setTick(performance.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const refresh = React.useCallback(async () => {
    if (sending.current) return
    sending.current = true; setBusy(true)
    try { await read(true) } finally { sending.current = false; setBusy(false) }
  }, [read])
  const current = saved && saved.token === token ? saved : null
  const data = current?.data ?? null
  const elapsed = current ? Math.max(0, (tick - current.at) / 1000) : 0
  return <Context.Provider value={{ data, busy, failed, elapsed, read, refresh }}>{children}</Context.Provider>
}

export function AccountUsagePanel() {
  const { data, busy, failed, elapsed, read, refresh } = React.useContext(Context)
  const status = data?.refresh?.status ?? "idle"
  const serverNow = data?.serverTime ? Date.parse(data.serverTime) + elapsed * 1000 : 0
  const deadline = data?.refresh?.nextAllowedAt ? Date.parse(data.refresh.nextAllowedAt) : 0
  const blocked = ["retry", "offline", "circuit"].includes(status) && deadline > serverNow
  const pending = busy || (status === "running" && (!deadline || deadline > serverNow))
  const ages = data?.snapshots.filter(s => s.runtime === "claude_code").flatMap(s => s.windows.flatMap(w => w.ageSeconds == null ? [] : [w.ageSeconds + elapsed])) ?? []
  const age = usageAge(ages.length ? Math.min(...ages) : null)
  const retry = failed || ["retry", "offline"].includes(status) || (status === "running" && !pending)
  const recentSuccess = status === "success" && data?.refresh?.completedAt && serverNow - Date.parse(data.refresh.completedAt) < 60_000
  const label = pending ? "请求中…" : status === "circuit" && blocked ? "今日探针已熔断，明日恢复" : retry ? "稍后重试" : status === "disabled" ? "未配置探针" : `${recentSuccess ? "成功" : "刷新"} · 数据 · ${age}`
  return <Popover onOpenChange={(open) => { if (open && !busy) void read() }}>
    <PopoverTrigger asChild><Button size="icon" variant="ghost" aria-label="查看账号用量" title="账号用量" className="size-9 shrink-0 rounded-full bg-muted text-muted-foreground"><Gauge className="size-6" aria-hidden="true" /></Button></PopoverTrigger>
    <PopoverContent side="top" align="start" aria-label="账号剩余用量" className="max-h-[min(70vh,32rem)] w-80 max-w-[calc(100vw-2rem)] gap-0 overflow-y-auto text-xs">
      <div className="mb-2 flex items-center justify-between"><span>账号用量</span><Button aria-label="刷新用量" size="sm" variant="ghost" disabled={pending || blocked || status === "disabled"} onClick={() => void refresh()}>{label}</Button></div>
      {status === "offline" && <p role="status">探针节点离线</p>}
      {(["retry", "offline", "circuit"].includes(status) && deadline > 0) && <p role="status">可重试时间：{localTime(data!.refresh!.nextAllowedAt!)}</p>}
      {failed && <p role="status">刷新失败，原有数据保留</p>}
      {["codex", "claude_code"].map(runtime => {
        const snapshots = data?.snapshots.filter(s => s.runtime === runtime) ?? []
        const name = runtime === "codex" ? "Codex" : "Claude Code"
        return <div key={runtime} className="mb-2 space-y-1">
          {!snapshots.length && <p>{name} · 暂无数据</p>}
          {snapshots.map(s => <div key={s.accountKey} className="space-y-1">
            <p>{name} · {s.accountLabel}{s.planType ? ` · ${s.planType}` : ""}</p>
            {s.windows.map((w, index) => <div key={`${w.kind}-${index}`}>
              <p>{windowLabel(w)} · 已用 {Math.round(100 - w.remainingPercent)}% · 剩余 {Math.round(w.remainingPercent)}%</p>
              {runtime === "claude_code" && <p>{w.source === "probe" ? "探针" : w.source === "event" ? "事件" : "旧缓存"} · {usageAge(w.ageSeconds == null ? null : w.ageSeconds + elapsed)}</p>}
              <p>报告重置时间：{localTime(w.resetsAt)}</p>
              <progress aria-label={`${name} ${windowLabel(w)}剩余`} value={w.remainingPercent} max={100} className="h-1 w-full accent-primary" />
            </div>)}
            {runtime !== "claude_code" && <p className="text-muted-foreground">{s.stale ? "数据已过期 · " : ""}{s.fetchedAt ? `${localTime(s.fetchedAt)} 更新` : "暂无数据"}</p>}
          </div>)}
        </div>
      })}
      <p className="text-muted-foreground">只有点击刷新才执行甲骨文探针；历史数据长期保留，年龄以服务器接收时间为准。</p>
    </PopoverContent>
  </Popover>
}

export function SessionUsageNotice({ connectorId, runtimeId }: { connectorId: string; runtimeId?: string }) {
  const { data, elapsed } = React.useContext(Context)
  const matches = data?.snapshots.filter(s => s.bindings.some(b => b.connectorId === connectorId && b.runtimeId === runtimeId)) ?? []
  const now = data?.serverTime ? Date.parse(data.serverTime) + elapsed * 1000 : Date.now()
  return <>{matches.flatMap(s => s.windows.filter(w => w.kind === "five_hour" && w.remainingPercent <= 20 && Date.parse(w.resetsAt) > now).map((w, index) =>
    <div role="status" key={`${s.accountKey}-${index}`} className={`px-4 py-2 text-sm ${w.remainingPercent === 0 ? "bg-amber-100 text-amber-950 dark:bg-amber-950 dark:text-amber-100" : "bg-muted"}`}>
      {s.runtime === "codex" ? "Codex" : "Claude Code"} 5 小时窗口仅剩 {Math.round(w.remainingPercent)}%，{localTime(w.resetsAt)} 重置{s.stale ? "（数据已过期）" : ""}
    </div>))}</>
}
