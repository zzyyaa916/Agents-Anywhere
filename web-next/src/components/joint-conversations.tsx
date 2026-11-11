"use client"

import * as React from "react"
import { Minimize2, Maximize2, X } from "lucide-react"
import { useAuth } from "@/components/auth/auth-context"
import { useWorkspace } from "@/components/workspace-context"
import { SessionDetail } from "@/components/session-detail"
import { useSessionForward } from "@/components/session/session-forward"
import { TaskGroupConversation } from "@/components/task-groups"
import { Button } from "@/components/ui/button"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Textarea } from "@/components/ui/textarea"
import { dashboardApi } from "@/features/dashboard/api"
import type { SessionView } from "@/features/dashboard/types"
import { taskGroupsApi, type TaskGroup } from "@/features/task-groups/api"
import { conversationServer, conversationScope, readConversationState, writeConversationState } from "@/features/task-groups/conversation-storage"
import { useConversationBroadcast } from "@/features/task-groups/use-conversation-broadcast"

type PaneMode = "open" | "minimized" | "closed"
type View = { projectId: string; groupId: string; sessionIds: string[]; joined: boolean; panes: Record<string, PaneMode> }
const identity = (session: SessionView) => session.runtimeId || session.runtimeType || session.runtime
const agentName = (session: SessionView) => session.runtimeName || session.runtimeTypeDisplayName || session.runtimeType || session.runtime

export function JointConversations() {
  const { session } = useAuth()
  const scope = conversationScope(session?.userId ?? "", conversationServer(session))
  return <JointWorkspace key={scope} scope={scope} token={session?.accessToken ?? ""} />
}

function JointWorkspace({ scope, token }: { scope: string; token: string }) {
  const { projects, sessions: inventorySessions, jointGroupId, navigate, upsertSession } = useWorkspace()
  const storageKey = `${scope}:workspace`
  const [view, setView] = React.useState<View>(() => {
    const saved = readConversationState(storageKey)
    const panes = saved.panes && typeof saved.panes === "object" ? Object.fromEntries(Object.entries(saved.panes).filter(([, value]) => ["open", "minimized", "closed"].includes(String(value)))) : {}
    return {
      projectId: projects.some(row => row.id === saved.projectId) ? String(saved.projectId) : projects[0]?.id ?? "",
      groupId: jointGroupId || (typeof saved.groupId === "string" ? saved.groupId : ""),
      sessionIds: Array.isArray(saved.sessionIds) ? saved.sessionIds.filter((id): id is string => typeof id === "string").slice(0, 2) : [],
      joined: saved.joined === true,
      panes,
    }
  })
  const [projectSessions, setProjectSessions] = React.useState<SessionView[]>([])
  const [groups, setGroups] = React.useState<TaskGroup[]>([])
  const [group, setGroup] = React.useState<TaskGroup | null>(null)
  const [error, setError] = React.useState("")
  const [loading, setLoading] = React.useState(false)
  React.useEffect(() => {
    if (!writeConversationState(storageKey, view)) setError("无法保存联立选择，请保持当前页面打开。")
  }, [storageKey, view])
  React.useEffect(() => {
    if (jointGroupId) setView(current => current.groupId === jointGroupId ? current : { ...current, groupId: jointGroupId, joined: false })
  }, [jointGroupId])
  React.useEffect(() => {
    if (!token || !view.projectId) return
    let cancelled = false
    setLoading(true); setError("")
    async function loadSessions() {
      const rows: SessionView[] = []
      const seen = new Set<string>()
      let cursor: string | null = null
      while (true) {
        const page = await dashboardApi.listProjectSessions(token, view.projectId, { archived: false, limit: 100, cursor })
        rows.push(...page.sessions)
        if (!page.hasMore) return rows
        if (!page.nextCursor || seen.has(page.nextCursor)) throw new Error("会话列表未能完整加载，请重试。")
        cursor = page.nextCursor; seen.add(cursor)
      }
    }
    void Promise.all([loadSessions(), taskGroupsApi.list(token, view.projectId)]).then(([rows, history]) => {
      if (!cancelled) { setProjectSessions(rows); setGroups(history.groups) }
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token, view.projectId, inventorySessions.length])
  React.useEffect(() => {
    setGroup(null)
    if (!view.groupId || !token) return
    let cancelled = false
    void taskGroupsApi.get(token, view.groupId).then(result => {
      if (cancelled) return
      setGroup(result)
      setView(current => ({ ...current, projectId: result.projectId }))
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [token, view.groupId])
  const updateSession = React.useCallback((row: SessionView) => {
    upsertSession(row)
    setProjectSessions(rows => rows.map(current => current.id === row.id ? row : current))
  }, [upsertSession])
  const project = projects.find(row => row.id === view.projectId)
  const available = projectSessions.filter(row => row.projectId === view.projectId && row.connectorId === project?.connectorId && !row.archived && row.sourceAvailability !== "deleted")
  const selected = view.sessionIds.flatMap(id => available.find(row => row.id === id) ? [available.find(row => row.id === id)!] : [])
  const validPair = selected.length === 2 && selected[0]!.id !== selected[1]!.id && identity(selected[0]!) !== identity(selected[1]!)
  function chooseSession(index: number, id: string) {
    setView(current => {
      const ids = [...current.sessionIds]; ids[index] = id
      return { ...current, sessionIds: ids, joined: false }
    })
  }
  function closeGroup() {
    setView(current => ({ ...current, groupId: "", joined: false })); navigate("joint")
  }
  return <div className="flex h-full min-h-0 min-w-0 flex-col overflow-auto p-4">
    <div className="shrink-0 space-y-3 pb-3">
      <h1 className="text-lg font-medium">联立会话</h1>
      <p className="text-sm text-muted-foreground">选择同项目中两个不同 AI 的已有会话，分别聊天或统一发布；切换页面后可从侧栏恢复。</p>
      <label className="grid gap-1 text-sm">项目<NativeSelect aria-label="联立项目" value={view.projectId} onChange={e => {
        const projectId = e.target.value
        setView({ projectId, groupId: "", sessionIds: [], joined: false, panes: {} }); navigate("joint")
      }}>{!projects.length && <NativeSelectOption value="">暂无项目</NativeSelectOption>}{projects.map(row => <NativeSelectOption key={row.id} value={row.id}>{row.name}</NativeSelectOption>)}</NativeSelect></label>
      <div className="flex flex-wrap items-end gap-3">
        {[0, 1].map(index => <label key={index} className="grid min-w-56 flex-1 gap-1 text-sm">会话 {index + 1}<NativeSelect aria-label={`联立会话 ${index + 1}`} value={view.sessionIds[index] ?? ""} disabled={loading} onChange={e => chooseSession(index, e.target.value)}>
          <NativeSelectOption value="">选择已有 AI 会话</NativeSelectOption>
          {available.map(row => <NativeSelectOption key={row.id} value={row.id} disabled={Boolean(view.sessionIds[1 - index] && available.some(other => other.id === view.sessionIds[1 - index] && identity(other) === identity(row)))}>{agentName(row)} · {row.title || row.id}</NativeSelectOption>)}
        </NativeSelect></label>)}
        <Button disabled={loading || !validPair} onClick={() => { setView(current => ({ ...current, groupId: "", joined: true })); navigate("joint") }}>联立显示</Button>
      </div>
      {groups.length > 0 && <label className="grid gap-1 text-sm">恢复多 AI 任务<NativeSelect aria-label="恢复多 AI 任务" value={view.groupId} onChange={e => {
        const groupId = e.target.value
        setView(current => ({ ...current, groupId, joined: false })); navigate("joint", groupId || undefined)
      }}><NativeSelectOption value="">选择已有多 AI 任务</NativeSelectOption>{groups.filter(row => row.phase === "ready").map(row => <NativeSelectOption key={row.id} value={row.id}>{row.request.content.slice(0, 60) || row.id}</NativeSelectOption>)}</NativeSelect></label>}
      {loading && <p role="status">正在加载项目会话…</p>}
      {error && <p role="alert" className="whitespace-pre-wrap text-sm text-destructive">{error}</p>}
      {view.joined && !loading && !validPair && <p role="alert">已选会话不可用或属于同一个 AI，请重新选择。</p>}
    </div>
    {view.groupId ? (group?.id === view.groupId ? <TaskGroupConversation key={group.id} initialGroup={group} onBack={closeGroup} /> : !error && <p role="status">正在恢复多 AI 会话…</p>) : null}
    {!view.groupId && view.joined && validPair && <PairedConversations key={view.sessionIds.join(",")} scope={scope} token={token} sessions={selected} modes={view.panes}
      onModeChange={(id, mode) => setView(current => ({ ...current, panes: { ...current.panes, [id]: mode } }))} onSessionUpdated={updateSession} />}
  </div>
}

function PairedConversations({ scope, token, sessions, modes, onModeChange, onSessionUpdated }: {
  scope: string; token: string; sessions: SessionView[]; modes: Record<string, PaneMode>
  onModeChange: (id: string, mode: PaneMode) => void; onSessionUpdated: (row: SessionView) => void
}) {
  const broadcast = useConversationBroadcast(`${scope}:pair:${sessions.map(row => row.id).join(",")}`, sessions.map(row => row.id))
  const visible = sessions.filter(row => modes[row.id] !== "closed")
  return <div className="min-w-0 space-y-3">
    <div className="flex gap-2">{sessions.filter(row => modes[row.id] === "closed").map(row => <Button key={row.id} variant="outline" size="sm" onClick={() => onModeChange(row.id, "open")}>重新打开 · {agentName(row)}</Button>)}</div>
    <div className="overflow-x-auto"><div data-joint-grid className="grid items-start gap-3" style={{ gridTemplateColumns: visible.map(row => modes[row.id] === "minimized" ? "minmax(190px,0.35fr)" : "minmax(320px,1fr)").join(" ") }}>
      {sessions.map(row => <ExistingSessionPane key={row.id} token={token} session={row} mode={modes[row.id] ?? "open"} onModeChange={mode => onModeChange(row.id, mode)} onSessionUpdated={onSessionUpdated} onQueueReady={broadcast.registerQueue(row.id)} />)}
    </div></div>
    <label className="grid gap-2 text-sm">联立发布（同时发送到已选的两个 AI）<Textarea aria-label="联立发布" value={broadcast.draft} maxLength={32000} disabled={broadcast.sending} onChange={e => broadcast.setDraft(e.target.value)} /></label>
    {broadcast.error && <p role="alert" className="text-sm text-destructive">{broadcast.error}</p>}
    <p className="text-xs text-muted-foreground">各会话独立发送或进入自己的消息队列；不会互相复制私有上下文。</p>
    <Button disabled={!broadcast.ready || broadcast.sending || !broadcast.draft.trim()} onClick={() => void broadcast.send()}>统一发送</Button>
  </div>
}

function ExistingSessionPane({ token, session, mode, onModeChange, onSessionUpdated, onQueueReady }: {
  token: string; session: SessionView; mode: PaneMode; onModeChange: (mode: PaneMode) => void
  onSessionUpdated: (row: SessionView) => void; onQueueReady: (enqueue: ((text: string) => boolean) | null) => void
}) {
  const { connectors, reportSessionStreamProgress } = useWorkspace()
  const forward = useSessionForward(token, session, true, true)
  return <article data-joint-session={session.id} className={`${mode === "closed" ? "hidden" : "flex"} min-w-0 flex-col overflow-hidden rounded-lg border ${mode === "open" ? "h-[60dvh] min-h-80" : ""}`}>
    <header className="flex shrink-0 items-center justify-between gap-2 border-b p-2">
      <div className="min-w-0"><h2 className="truncate text-sm font-medium">{agentName(session)}</h2><p className="truncate text-xs text-muted-foreground">{session.title}</p></div>
      <div className="flex items-center gap-1">{forward.control}
        <Button variant="ghost" size="icon-sm" aria-label={mode === "minimized" ? "展开会话" : "收起会话"} onClick={() => onModeChange(mode === "minimized" ? "open" : "minimized")}>{mode === "minimized" ? <Maximize2 /> : <Minimize2 />}</Button>
        <Button variant="ghost" size="icon-sm" aria-label="隐藏会话窗口" onClick={() => onModeChange("closed")}><X /></Button>
      </div>
    </header>
    <div className={mode === "minimized" ? "hidden" : "min-h-0 flex-1"}>
      <SessionDetail token={token} sessionId={session.id} fallbackSession={session} connectorDeviceOs={connectors.find(row => row.id === session.connectorId)?.deviceOs}
        onSessionUpdated={onSessionUpdated} onStreamProgress={reportSessionStreamProgress} onQueueReady={onQueueReady} onForwardCommand={forward.handleCommand} />
    </div>
  </article>
}
