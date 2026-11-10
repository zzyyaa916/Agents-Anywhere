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
import { CAPABILITY, capabilityIsUsable, findCapability } from "@/components/session/capabilities"
import { catalogItemEnabled, selectionIdForModelCatalog } from "@/components/session/catalog-selection"
import { parseForwardCommand } from "@/features/task-groups/forward-command"
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
  const queues = React.useRef(new Map<string, (text: string) => boolean>())
  const queueCallbacks = React.useRef(new Map<string, (enqueue: ((text: string) => boolean) | null) => void>())
  const registerQueue = (id: string) => {
    if (!queueCallbacks.current.has(id)) queueCallbacks.current.set(id, enqueue => {
      if (enqueue) queues.current.set(id, enqueue)
      else queues.current.delete(id)
    })
    return queueCallbacks.current.get(id)!
  }
  const broadcastReady = current.candidates.every(row => row.phase === "sent" && row.sessionId)
  async function sendBroadcast() {
    if (sending || !broadcastReady || !broadcast.trim()) return
    if (delivery.current?.content !== broadcast) delivery.current = { content: broadcast, ids: new Map(), sent: new Set() }
    const batch = delivery.current!
    setSending(true); setError("")
    try {
      for (const candidate of current.candidates) {
        const id = candidate.sessionId!
        if (batch.sent.has(id)) continue
        if (!queues.current.get(id)?.(batch.content)) throw new Error(t("broadcastFailed"))
        batch.sent.add(id)
      }
      setBroadcast(""); delivery.current = null
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setSending(false) }
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
          {panes.map(pane => <TaskGroupChatPane key={pane.key} group={pane.group} slot={pane.slot} title={paneTitle(pane)} token={token}
            onQueueReady={pane.candidate.sessionId ? registerQueue(pane.candidate.sessionId) : undefined}
            onForwardCommand={async (text, attachments) => {
              const command = parseForwardCommand(text, available.flatMap(runtime => [runtime.runtimeId, runtime.runtimeType, runtime.name, runtime.displayName].filter((name): name is string => Boolean(name))))
              if (!command) return null
              const matches = available.filter(runtime => [runtime.runtimeId, runtime.runtimeType, runtime.name, runtime.displayName].some(name => name?.toLowerCase() === command.target.toLowerCase()))
              if (matches.length !== 1) { setError("目标 AI 不存在或名称不唯一，请使用转发按钮选择。"); return false }
              const runtime = matches[0]!
              let target = current.request.candidates.find(row => row.runtimeId === runtime.runtimeId)
              const signature = JSON.stringify([pane.key, command, attachments.map(file => file.uploaded?.fileId)])
              if (forwardIdentity.current.signature !== signature) forwardIdentity.current = { signature, id: operationId() }
              const forwardOperationId = forwardIdentity.current.id
              try {
                if (!target) {
                  const { capabilitySet } = await dashboardApi.getConnectorRuntimeCapabilities(token, project!.connectorId, runtime.runtimeId)
                  const scope = { runtimeId: runtime.runtimeId, runtimeType: runtime.runtimeType }
                  for (const id of [CAPABILITY.modelCatalog, CAPABILITY.permissionCatalog]) {
                    if (findCapability(capabilitySet, id, scope)?.supported && !capabilityIsUsable(capabilitySet, id, scope)) throw new Error("目标 AI 设置暂不可用，请稍后重试。")
                  }
                  const selections: Record<string, string | null> = {}
                  if (capabilityIsUsable(capabilitySet, CAPABILITY.modelCatalog, scope)) {
                    const { catalog } = await dashboardApi.getConnectorRuntimeModelCatalog(token, project!.connectorId, runtime.runtimeId)
                    const model = catalog.models.find(row => row.default && catalogItemEnabled(row)) ?? catalog.models.find(catalogItemEnabled)
                    const reasoning = model?.reasoningItems.find(row => row.default && catalogItemEnabled(row)) ?? model?.reasoningItems.find(catalogItemEnabled)
                    const selected = selectionIdForModelCatalog(catalog, model?.id ?? "", reasoning?.id ?? "")
                    if (!selected) throw new Error("目标 AI 没有可用模型，请使用转发按钮检查设置。")
                    selections.model = selected
                  }
                  if (capabilityIsUsable(capabilitySet, CAPABILITY.permissionCatalog, scope)) {
                    const { catalog } = await dashboardApi.getConnectorRuntimePermissionCatalog(token, project!.connectorId, runtime.runtimeId)
                    const permission = catalog.permissions.find(row => row.default && catalogItemEnabled(row)) ?? catalog.permissions.find(catalogItemEnabled)
                    if (!permission) throw new Error("目标 AI 没有可用权限，请使用转发按钮检查设置。")
                    selections.permission = permission.selectionId
                  }
                  target = { runtime: runtime.runtimeType, runtimeId: runtime.runtimeId, selections }
                }
                if (attachments.some(file => !file.uploaded)) throw new Error("请等待附件上传完成。")
                const group = await taskGroupsApi.handoff(token, pane.group.id, { operationId: forwardOperationId, slot: pane.slot, mode: "continue", target, instructions: command.instructions, attachments: attachments.map(file => ({ fileId: file.uploaded!.fileId })) })
                setForwarded(rows => [...rows.filter(row => row.id !== group.id), group])
                updateGroup(await taskGroupsApi.start(token, group.id, 0))
                await refreshData()
                if (forwardIdentity.current.id === forwardOperationId) forwardIdentity.current = { signature: "", id: "" }
                return true
              } catch (e) { setError(e instanceof Error ? e.message : String(e)); return false }
            }}
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
