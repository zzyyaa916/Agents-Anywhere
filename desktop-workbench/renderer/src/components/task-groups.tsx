"use client"

import * as React from "react"
import { useTranslations } from "next-intl"
import { TaskGroupForwardDialog } from "@/components/task-group-forward-dialog"
import { conversationServer, conversationScope, readConversationState, writeConversationState } from "@/features/task-groups/conversation-storage"
import { useConversationBroadcast } from "@/features/task-groups/use-conversation-broadcast"
import { forwardToTargets } from "@/features/task-groups/forward-to-targets"
import { dashboardApi } from "@/features/dashboard/api"
import type { DeviceRuntimeView } from "@/features/dashboard/types"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/components/auth/auth-context"
import { useWorkspace } from "@/components/workspace-context"
import { TaskGroupChatPane, type ChatPaneMode } from "@/components/task-group-chat-pane"
import { forwardRuntimeNames, resolveForwardTargets } from "@/features/task-groups/forward-targets"
import { parseForwardCommand } from "@/features/task-groups/forward-command"
import { taskGroupsApi, type TaskGroup, type CandidateDiff, type CandidateTarget } from "@/features/task-groups/api"


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
  const viewScope = `${conversationScope(session?.userId ?? "", conversationServer(session))}:group:${initialGroup.id}`
  const [paneModes, setPaneModes] = React.useState<Record<string, ChatPaneMode>>(() => {
    const modes = readConversationState(viewScope).panes
    return modes && typeof modes === "object" ? Object.fromEntries(Object.entries(modes).filter(([, mode]) => ["open", "minimized", "closed"].includes(String(mode)))) : {}
  })
  React.useEffect(() => { writeConversationState(viewScope, { panes: paneModes }) }, [viewScope, paneModes])
  const [forward, setForward] = React.useState<{ group: TaskGroup; slot: number; conclusion: string } | null>(null)
  const [instructions, setInstructions] = React.useState("")
  const forwardOperations = React.useRef(new Map<string, string>())
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
      if (disposed) return
      const related = new Set([initialGroup.id])
      let previousSize = 0
      while (previousSize !== related.size) {
        previousSize = related.size
        for (const row of result.groups) if (row.request.source && related.has(row.request.source.groupId)) related.add(row.id)
      }
      setForwarded(result.groups.filter(row => row.id !== initialGroup.id && related.has(row.id)))
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

  async function sendForward(targets: CandidateTarget[], instructions: string, attachments: { fileId: string }[]) {
    if (!forward) return
    const turn = generation.current
    const source = forward
    await forwardToTargets({ token, source: `${source.group.id}:${source.slot}`, targets, instructions, attachments, operations: forwardOperations.current, operationScope: `${viewScope}:forward:${source.group.id}:${source.slot}`,
      create: (target, operationId) => taskGroupsApi.handoff(token, source.group.id, { slot: source.slot, mode: "continue", target, instructions, attachments, operationId }),
      onUpdate: group => {
        if (turn !== generation.current) return
        setForwarded(rows => [...rows.filter(row => row.id !== group.id), group])
        setPaneModes(rows => ({ ...rows, [`${group.id}:0`]: "open" }))
      },
    })
    if (turn !== generation.current) return
    setForward(null); await refreshData()
  }

  const broadcastSessionIds = current.candidates.flatMap(row => row.phase === "sent" && row.sessionId ? [row.sessionId] : [])
  const broadcastState = useConversationBroadcast(`${viewScope}:broadcast`, broadcastSessionIds)
  const { draft: broadcast, setDraft: setBroadcast, sending, registerQueue } = broadcastState
  const broadcastReady = broadcastState.ready && broadcastSessionIds.length === current.candidates.length
  const sendBroadcast = broadcastState.send

  const panes = current ? [current, ...forwarded].flatMap(group => group.candidates.map((candidate, slot) => ({ group, candidate, slot, key: `${group.id}:${slot}` }))) : []
  const hasChat = panes.some(pane => pane.candidate.sessionId)
  const visible = panes.filter(pane => paneModes[pane.key] !== "closed")
  const paneTitle = (pane: typeof panes[number]) => {
    const configured = pane.group.request.candidates[pane.slot]
    const runtime = available.find(item => item.runtimeId === configured?.runtimeId)
    return runtime?.name || runtime?.displayName || configured?.runtimeId || configured?.runtime || "AI"
  }

  return <div className="min-h-0 min-w-0 flex-1 space-y-3 overflow-auto p-3">
    <Button variant="ghost" size="sm" disabled={starting} onClick={onBack}>{t("backToComposer")}</Button>
    {(error || broadcastState.error) && <p role="alert" className="text-sm text-destructive">{error || broadcastState.error}</p>}
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
          {panes.map(pane => <TaskGroupChatPane key={pane.key} group={pane.group} slot={pane.slot} title={paneTitle(pane)} token={token}
            onQueueReady={pane.candidate.sessionId ? registerQueue(pane.candidate.sessionId) : undefined}
            onForwardCommand={async (text, attachments) => {
              const command = parseForwardCommand(text, available.flatMap(forwardRuntimeNames))
              if (!command) return null
              try {
                if (attachments.some(file => !file.uploaded)) throw new Error("请等待附件上传完成。")
                const targets = await resolveForwardTargets(token, project!.connectorId, available, command.targets, current.request.candidates)
                const refs = attachments.map(file => ({ fileId: file.uploaded!.fileId }))
                await forwardToTargets({ token, source: pane.key, targets, instructions: command.instructions, attachments: refs, operations: forwardOperations.current, operationScope: `${viewScope}:forward:${pane.group.id}:${pane.slot}`,
                  create: (target, operationId) => taskGroupsApi.handoff(token, pane.group.id, { operationId, slot: pane.slot, mode: "continue", target, instructions: command.instructions, attachments: refs }),
                  onUpdate: group => setForwarded(rows => [...rows.filter(row => row.id !== group.id), group]),
                })
                await refreshData()
                return true
              } catch (e) { setError(e instanceof Error ? e.message : String(e)); return false }
            }}
            mode={paneModes[pane.key] ?? "open"} pending={pending} diff={diffs[pane.key]}
            onModeChange={mode => setPaneModes(rows => ({ ...rows, [pane.key]: mode }))}
            onForward={conclusion => { setForward({ group: pane.group, slot: pane.slot, conclusion }); setInstructions("") }}
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
    {forward && <TaskGroupForwardDialog key={`${forward.group.id}:${forward.slot}`} token={token} connectorId={project!.connectorId}
      sessionId={forward.group.candidates[forward.slot]!.sessionId!} runtimes={available.filter(row => row.runtimeId !== forward.group.request.candidates[forward.slot]?.runtimeId)}
      initialRuntimeId={available.find(r => r.runtimeId !== forward.group.request.candidates[forward.slot]?.runtimeId)?.runtimeId}
      initialInstructions={instructions} conclusion={forward.conclusion} pending={pending} error={error}
      onClose={() => setForward(null)} onSend={(targets, instructions, attachments) => run(() => sendForward(targets, instructions, attachments))} />}

  </div>
}
