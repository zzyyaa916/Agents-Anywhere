"use client"

import * as React from "react"
import { useTranslations } from "next-intl"
import { TaskGroupAgentSelect } from "@/components/task-group-agent-select"
import { dashboardApi } from "@/features/dashboard/api"
import type { DeviceRuntimeView } from "@/features/dashboard/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/components/auth/auth-context"
import { useWorkspace } from "@/components/workspace-context"
import { TaskGroupChatPane, type ChatPaneMode } from "@/components/task-group-chat-pane"
import { createClientId } from "@/lib/id"
import { taskGroupsApi, type TaskGroup, type CandidateDiff, type CandidateTarget } from "@/features/task-groups/api"

const operationId = () => createClientId("group").replaceAll("_", "-")

export function TaskGroupConversation({ initialGroup, starting = false, onBack }: { initialGroup: TaskGroup; starting?: boolean; onBack: () => void }) {
  const t = useTranslations("taskGroups")
  const { session } = useAuth()
  const { refreshData, projects } = useWorkspace()
  const project = projects.find(row => row.id === initialGroup.projectId)
  const token = session?.accessToken ?? ""
  const [runtimes, setRuntimes] = React.useState<DeviceRuntimeView[]>([])
  const [current, setCurrent] = React.useState<TaskGroup>(initialGroup)
  const [forwarded, setForwarded] = React.useState<TaskGroup[]>([])
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState("")
  const [diffs, setDiffs] = React.useState<Record<string, CandidateDiff>>({})
  const [paneModes, setPaneModes] = React.useState<Record<string, ChatPaneMode>>({})
  const [forward, setForward] = React.useState<{ group: TaskGroup; slot: number; conclusion: string } | null>(null)
  const [forwardTarget, setForwardTarget] = React.useState<CandidateTarget | null>(null)
  const [instructions, setInstructions] = React.useState("")
  const forwardIdentity = React.useRef({ signature: "", id: "" })
  const available = runtimes.filter(r => r.connectorId === project?.connectorId && r.status === "running")
  React.useEffect(() => {
    let cancelled = false
    setRuntimes([])
    if (project?.connectorId && token) void dashboardApi.getConnectorRuntimes(token, project.connectorId)
      .then(result => { if (!cancelled) setRuntimes(result.runtimes) })
      .catch(e => { if (!cancelled) setError(String(e.message ?? e)) })
    return () => { cancelled = true }
  }, [project?.connectorId, token])
  const generation = React.useRef(0)
  const observedIds = [current?.id, ...forwarded.map(group => group.id)].filter(Boolean).join(",")

  React.useEffect(() => { setCurrent(initialGroup) }, [initialGroup])
  React.useEffect(() => {
    let disposed = false
    void taskGroupsApi.list(token, initialGroup.projectId).then(result => {
      if (!disposed) setForwarded(result.groups.filter(row => row.request.source?.groupId === initialGroup.id))
    }).catch(() => {})
    return () => { disposed = true; ++generation.current }
  }, [initialGroup.id, initialGroup.projectId, token])

  React.useEffect(() => {
    if (!observedIds || !token) return
    let disposed = false
    let fetching = false
    const timer = window.setInterval(async () => {
      if (fetching) return
      fetching = true
      try {
        const results = await Promise.allSettled(observedIds.split(",").map(id => taskGroupsApi.get(token, id)))
        if (disposed) return
        const fresh = new Map(results.flatMap(result => result.status === "fulfilled" ? [[result.value.id, result.value] as const] : []))
        setCurrent(row => row ? fresh.get(row.id) ?? row : row)
        setForwarded(rows => rows.map(row => fresh.get(row.id) ?? row))
      } finally { fetching = false }
    }, 5000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [observedIds, token])

  async function run(action: () => Promise<void>) {
    const turn = generation.current
    setPending(true); setError("")
    try { await action() } catch (e) {
      if (turn === generation.current) setError(e instanceof Error ? e.message : String(e))
    } finally { if (turn === generation.current) setPending(false) }
  }

  function updateGroup(group: TaskGroup) {
    setCurrent(row => row?.id === group.id ? group : row)
    setForwarded(rows => rows.map(row => row.id === group.id ? group : row))
  }

  async function sendForward() {
    if (!forward || !forwardTarget || !instructions.trim()) return
    const body = { slot: forward.slot, mode: "continue" as const, target: forwardTarget, instructions: instructions.trim() }
    const signature = JSON.stringify([forward.group.id, body])
    if (forwardIdentity.current.signature !== signature) forwardIdentity.current = { signature, id: operationId() }
    const turn = generation.current
    const group = await taskGroupsApi.handoff(token, forward.group.id, { ...body, operationId: forwardIdentity.current.id })
    if (turn !== generation.current) return
    setForwarded(rows => [...rows.filter(row => row.id !== group.id), group])
    setPaneModes(rows => ({ ...rows, [`${group.id}:0`]: "open" }))
    const started = await taskGroupsApi.start(token, group.id, 0)
    if (turn !== generation.current) return
    updateGroup(started); setForward(null); await refreshData()
  }

  const [broadcast, setBroadcast] = React.useState("")
  const [sending, setSending] = React.useState(false)
  const delivery = React.useRef<{ content: string; ids: Map<string, string>; sent: Set<string> } | null>(null)
  const broadcastReady = current.candidates.every(row => row.phase === "sent" && row.status === "idle" && row.sessionId)
  async function sendBroadcast() {
    const sessions = current.candidates.map(row => row.sessionId)
    if (sending || !broadcastReady || !broadcast.trim() || sessions.some(id => !id)) return
    if (delivery.current?.content !== broadcast) delivery.current = { content: broadcast, ids: new Map(), sent: new Set() }
    const batch = delivery.current!
    setSending(true); setError("")
    setCurrent(row => ({ ...row, candidates: row.candidates.map(candidate => ({ ...candidate, status: "pending" })) }))
    try {
      const results = await Promise.allSettled(sessions.map(async id => {
        if (!id || batch.sent.has(id)) return
        if (!batch.ids.has(id)) batch.ids.set(id, createClientId("message"))
        const result = await dashboardApi.sendSessionMessage(token, id, batch.content, { clientMessageId: batch.ids.get(id) })
        if (!result.ok) throw new Error(t("broadcastFailed"))
        batch.sent.add(id)
      }))
      if (results.some(row => row.status === "rejected")) throw new Error(t("broadcastFailed"))
      setBroadcast(""); delivery.current = null
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally {
      try { updateGroup(await taskGroupsApi.get(token, current.id)) } catch { /* Polling refreshes status after reconnect. */ }
      setSending(false)
    }
  }

  const panes = current ? [current, ...forwarded].flatMap(group => group.candidates.map((candidate, slot) => ({ group, candidate, slot, key: `${group.id}:${slot}` }))) : []
  const hasChat = panes.some(pane => pane.candidate.sessionId)
  const visible = panes.filter(pane => paneModes[pane.key] !== "closed")
  const paneTitle = (pane: typeof panes[number]) => {
    const configured = pane.group.request.candidates[pane.slot]
    const runtime = available.find(item => item.runtimeId === configured?.runtimeId)
    return `${t("candidate", { n: panes.findIndex(item => item.key === pane.key) + 1 })} · ${runtime?.name || runtime?.displayName || configured?.runtime}`
  }

  return <div className="min-h-0 min-w-0 flex-1 space-y-3 overflow-auto p-3">
    <Button variant="ghost" size="sm" disabled={starting} onClick={onBack}>{t("backToComposer")}</Button>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {current && <section className="min-w-0 space-y-3 border-t pt-3">
      <p className="whitespace-pre-wrap text-sm">{current.request.content}</p>
      <details><summary className="cursor-pointer text-xs text-muted-foreground">{t("base")}</summary><p className="break-all text-xs">{current.base ?? t("preparing")}</p></details>
      {current.handoffBrief && <details><summary className="cursor-pointer text-sm">{t("handoffPreview")}</summary><pre className="max-h-60 overflow-auto whitespace-pre-wrap text-xs">{current.handoffBrief}</pre></details>}
      {!starting && current.candidates.some(candidate => candidate.phase === "pending") && <Button disabled={pending || current.phase !== "ready"} onClick={() => void run(async () => {
        const id = current.id
        const turn = generation.current
        const results = await Promise.allSettled(current.candidates.map((candidate, slot) => candidate.phase === "pending" ? taskGroupsApi.start(token, id, slot) : Promise.resolve(null)))
        if (turn !== generation.current) return
        updateGroup(await taskGroupsApi.get(token, id)); await refreshData()
        if (results.some(result => result.status === "rejected")) throw new Error(t("checkBeforeRetry"))
      })}>{t("start")}</Button>}
      {!hasChat && <p className="text-sm text-muted-foreground">{t("readyToStart", { n: current.candidates.length })}</p>}
      {hasChat && <>
        <p className="text-xs text-muted-foreground">{t("windowHint")}</p>
        <div className="flex flex-wrap gap-2">{panes.filter(pane => paneModes[pane.key] === "closed").map(pane => <Button key={pane.key} variant="outline" size="sm" onClick={() => setPaneModes(rows => ({ ...rows, [pane.key]: "open" }))}>{t("reopen")} · {paneTitle(pane)}</Button>)}</div>
        <div className="overflow-x-auto"><div className="grid items-start gap-3" data-chat-grid style={{ gridTemplateColumns: visible.map(pane => paneModes[pane.key] === "minimized" ? "minmax(190px,0.35fr)" : "minmax(320px,1fr)").join(" ") }}>
          {visible.map(pane => <TaskGroupChatPane key={pane.key} group={pane.group} slot={pane.slot} title={paneTitle(pane)} token={token}
            mode={paneModes[pane.key] ?? "open"} pending={pending} diff={diffs[pane.key]}
            onModeChange={mode => setPaneModes(rows => ({ ...rows, [pane.key]: mode }))}
            onForward={conclusion => { setForward({ group: pane.group, slot: pane.slot, conclusion }); setForwardTarget(null); setInstructions(""); forwardIdentity.current = { signature: "", id: "" } }}
            onInspect={() => void run(async () => { const turn = generation.current; const result = await taskGroupsApi.diff(token, pane.group.id, pane.slot); if (turn === generation.current) setDiffs(rows => ({ ...rows, [pane.key]: result })) })}
            onSelect={() => void run(async () => updateGroup(await taskGroupsApi.select(token, pane.group.id, pane.slot)))} />)}
        </div></div>
        <div className="space-y-2 rounded-xl border bg-card p-3">
          <Label className="grid gap-2">{t("broadcastLabel", { n: current.candidates.length })}<Textarea aria-label={t("broadcastLabel", { n: current.candidates.length })}
            value={broadcast} disabled={sending} onChange={e => setBroadcast(e.target.value)} placeholder={t("broadcastPlaceholder")} maxLength={32000}
            onKeyDown={e => { if (!e.nativeEvent.isComposing && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendBroadcast() } }} /></Label>
          {!broadcastReady && <p className="text-xs text-muted-foreground">{t("broadcastWait")}</p>}
          <Button disabled={sending || !broadcastReady || !broadcast.trim()} onClick={() => void sendBroadcast()}>{t("broadcastSend")}</Button>
        </div>
      </>}
    </section>}
    <Dialog open={Boolean(forward)} onOpenChange={open => { if (!open && !pending) setForward(null) }}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader><DialogTitle>{t("forward")}</DialogTitle><DialogDescription>{t("forwardDescription")}</DialogDescription></DialogHeader>
        {forward && <TaskGroupAgentSelect key={`${forward.group.id}:${forward.slot}`} token={token} connectorId={project!.connectorId} runtimes={available}
          initialRuntimeId={available.find(r => r.runtimeId !== forward.group.request.candidates[forward.slot]?.runtimeId)?.runtimeId}
          label={t("handoffAgent")} disabled={pending} onChange={setForwardTarget} />}
        <details><summary className="cursor-pointer text-sm">{t("conclusion")}</summary><p className="max-h-48 overflow-auto whitespace-pre-wrap text-sm">{forward?.conclusion}</p></details>
        <Label className="grid gap-2">{t("forwardInstructions")}<Textarea aria-label={t("forwardInstructions")} value={instructions} maxLength={8000} disabled={pending} placeholder={t("forwardExample")} onChange={e => setInstructions(e.target.value)} /></Label>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter><Button variant="outline" disabled={pending} onClick={() => setForward(null)}>{t("cancel")}</Button><Button disabled={pending || !forwardTarget || !instructions.trim()} onClick={() => void run(sendForward)}>{t("sendForward")}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
}
