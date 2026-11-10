"use client"

import * as React from "react"
import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { useAuth } from "@/components/auth/auth-context"
import { useWorkspace } from "@/components/workspace-context"
import { TaskGroupChatPane, type ChatPaneMode } from "@/components/task-group-chat-pane"
import { createClientId } from "@/lib/id"
import { taskGroupsApi, type TaskGroup, type CandidateDiff, type CandidateTarget } from "@/features/task-groups/api"

const operationId = () => createClientId("group").replaceAll("_", "-")

export function TaskGroupsButton() {
  const [open, setOpen] = React.useState(false)
  const { session } = useAuth()
  const t = useTranslations("taskGroups")
  return <><Button variant="outline" size="sm" onClick={() => setOpen(true)}>{t("entry")}</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[94dvh] overflow-y-auto sm:max-w-[calc(100vw-2rem)]">
        <DialogHeader><DialogTitle>{t("title")}</DialogTitle><DialogDescription>{t("description")}</DialogDescription></DialogHeader>
        {open && <TaskGroupsWorkbench key={session?.userId} />}
      </DialogContent>
    </Dialog></>
}

function TaskGroupsWorkbench() {
  const t = useTranslations("taskGroups")
  const { session } = useAuth()
  const { projects, runtimes, newSessionProject, refreshData } = useWorkspace()
  const token = session?.accessToken ?? ""
  const [projectId, setProjectId] = React.useState(newSessionProject?.id ?? projects[0]?.id ?? "")
  const [content, setContent] = React.useState("")
  const [count, setCount] = React.useState(1)
  const [targets, setTargets] = React.useState<string[]>(["", "", ""])
  const [groups, setGroups] = React.useState<TaskGroup[]>([])
  const [current, setCurrent] = React.useState<TaskGroup | null>(null)
  const [forwarded, setForwarded] = React.useState<TaskGroup[]>([])
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState("")
  const [diffs, setDiffs] = React.useState<Record<string, CandidateDiff>>({})
  const [paneModes, setPaneModes] = React.useState<Record<string, ChatPaneMode>>({})
  const [forward, setForward] = React.useState<{ group: TaskGroup; slot: number; conclusion: string } | null>(null)
  const [forwardTarget, setForwardTarget] = React.useState("")
  const [instructions, setInstructions] = React.useState("")
  const identity = React.useRef({ signature: "", id: "" })
  const forwardIdentity = React.useRef({ signature: "", id: "" })
  const project = projects.find(p => p.id === projectId)
  const available = runtimes.filter(r => r.connectorId === project?.connectorId && r.status === "running")
  const generation = React.useRef(0)
  const observedIds = [current?.id, ...forwarded.map(group => group.id)].filter(Boolean).join(",")

  React.useEffect(() => {
    const turn = ++generation.current
    setCurrent(null); setForwarded([]); setForward(null); setDiffs({}); setPaneModes({}); setGroups([]); setError(""); setPending(false)
    if (projectId && token) void taskGroupsApi.list(token, projectId).then(result => {
      if (turn === generation.current) setGroups(result.groups)
    }).catch(e => { if (turn === generation.current) setError(String(e.message ?? e)) })
    return () => { ++generation.current }
  }, [projectId, token])

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

  function target(id: string): CandidateTarget {
    const runtime = available.find(r => r.runtimeId === id)
    if (!runtime) throw new Error(t("chooseAgents"))
    return { runtime: runtime.runtimeType, runtimeId: runtime.runtimeId, selections: {} }
  }

  function remember(group: TaskGroup) {
    setGroups(rows => [group, ...rows.filter(row => row.id !== group.id)])
  }

  function show(group: TaskGroup) {
    setCurrent(group); setDiffs({})
    setForwarded(groups.filter(row => row.request.source?.groupId === group.id))
    remember(group)
  }

  async function create() {
    const candidates = targets.slice(0, count).map(id => target(id || available[0]?.runtimeId || ""))
    const body = { projectId, content, candidates }
    const signature = JSON.stringify(body)
    if (identity.current.signature !== signature) identity.current = { signature, id: operationId() }
    const turn = generation.current
    const group = await taskGroupsApi.create(token, { ...body, operationId: identity.current.id })
    if (turn === generation.current) { show(group); await refreshData() }
  }

  function updateGroup(group: TaskGroup) {
    setCurrent(row => row?.id === group.id ? group : row)
    setForwarded(rows => rows.map(row => row.id === group.id ? group : row))
    remember(group)
  }

  async function sendForward() {
    if (!forward || !instructions.trim()) return
    const body = { slot: forward.slot, mode: "continue" as const, target: target(forwardTarget), instructions: instructions.trim() }
    const signature = JSON.stringify([forward.group.id, body])
    if (forwardIdentity.current.signature !== signature) forwardIdentity.current = { signature, id: operationId() }
    const turn = generation.current
    const group = await taskGroupsApi.handoff(token, forward.group.id, { ...body, operationId: forwardIdentity.current.id })
    if (turn !== generation.current) return
    setForwarded(rows => [...rows.filter(row => row.id !== group.id), group]); remember(group)
    setPaneModes(rows => ({ ...rows, [`${group.id}:0`]: "open" }))
    const started = await taskGroupsApi.start(token, group.id, 0)
    if (turn !== generation.current) return
    updateGroup(started); setForward(null); await refreshData()
  }

  const panes = current ? [current, ...forwarded].flatMap(group => group.candidates.map((candidate, slot) => ({ group, candidate, slot, key: `${group.id}:${slot}` }))) : []
  const hasChat = panes.some(pane => pane.candidate.sessionId)
  const visible = panes.filter(pane => paneModes[pane.key] !== "closed")
  const runtimeOptions = <><NativeSelectOption value="">{t("defaultAgent")}</NativeSelectOption>{available.map(r => <NativeSelectOption key={r.runtimeId} value={r.runtimeId}>{r.name || r.displayName} · {r.runtimeType}</NativeSelectOption>)}</>
  const paneTitle = (pane: typeof panes[number]) => {
    const configured = pane.group.request.candidates[pane.slot]
    const runtime = available.find(item => item.runtimeId === configured?.runtimeId)
    return `${t("candidate", { n: panes.findIndex(item => item.key === pane.key) + 1 })} · ${runtime?.name || runtime?.displayName || configured?.runtime}`
  }

  return <div className="min-w-0 space-y-4">
    <details open={!current} className="space-y-3">
      <summary className="cursor-pointer text-sm font-medium">{t("newTask")}</summary>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Label className="grid gap-2">{t("project")}<NativeSelect aria-label={t("project")} value={projectId} disabled={pending} onChange={e => setProjectId(e.target.value)}>
          {projects.map(p => <NativeSelectOption key={p.id} value={p.id}>{p.name}</NativeSelectOption>)}
        </NativeSelect></Label>
        <Label className="grid gap-2">{t("execution")}<NativeSelect aria-label={t("execution")} value={count} disabled={pending} onChange={e => setCount(Number(e.target.value))}>
          {[1, 2, 3].map(n => <NativeSelectOption key={n} value={n}>{t("agentCount", { n })}</NativeSelectOption>)}
        </NativeSelect></Label>
      </div>
      <Label className="grid gap-2">{t("task")}<Textarea aria-label={t("task")} maxLength={32000} value={content} disabled={pending} onChange={e => setContent(e.target.value)} placeholder={t("taskExample")} /></Label>
      <div className="grid gap-3 sm:grid-cols-3">{Array.from({ length: count }, (_, slot) => <Label key={slot} className="grid gap-2">{t("candidate", { n: slot + 1 })}
        <NativeSelect aria-label={t("candidate", { n: slot + 1 })} disabled={pending} value={targets[slot]} onChange={e => setTargets(rows => rows.map((value, n) => n === slot ? e.target.value : value))}>{runtimeOptions}</NativeSelect>
      </Label>)}</div>
      <p className="text-sm text-muted-foreground">{t("limits")}</p>
      <Button disabled={pending || !projectId || !content.trim() || !available.length} onClick={() => void run(create)}>{t("prepare")}</Button>
    </details>
    <Label className="grid gap-2">{t("history")}<NativeSelect disabled={pending} value={current?.id ?? ""} onChange={e => {
      const row = groups.find(g => g.id === e.target.value)
      if (row) void run(async () => show(await taskGroupsApi.get(token, row.id)))
    }}><NativeSelectOption value="">{t("chooseGroup")}</NativeSelectOption>{groups.map(g => <NativeSelectOption key={g.id} value={g.id}>{g.request.content.slice(0, 70)}</NativeSelectOption>)}</NativeSelect></Label>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {current && <section className="min-w-0 space-y-3 border-t pt-3">
      <p className="whitespace-pre-wrap text-sm">{current.request.content}</p>
      <details><summary className="cursor-pointer text-xs text-muted-foreground">{t("base")}</summary><p className="break-all text-xs">{current.base ?? t("preparing")}</p></details>
      {current.handoffBrief && <details><summary className="cursor-pointer text-sm">{t("handoffPreview")}</summary><pre className="max-h-60 overflow-auto whitespace-pre-wrap text-xs">{current.handoffBrief}</pre></details>}
      {current.candidates.some(candidate => candidate.phase === "pending") && <Button disabled={pending || current.phase !== "ready"} onClick={() => void run(async () => {
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
            onForward={conclusion => { setForward({ group: pane.group, slot: pane.slot, conclusion }); setForwardTarget(available.find(r => r.runtimeId !== pane.group.request.candidates[pane.slot]?.runtimeId)?.runtimeId ?? available[0]?.runtimeId ?? ""); setInstructions(""); forwardIdentity.current = { signature: "", id: "" } }}
            onInspect={() => void run(async () => { const turn = generation.current; const result = await taskGroupsApi.diff(token, pane.group.id, pane.slot); if (turn === generation.current) setDiffs(rows => ({ ...rows, [pane.key]: result })) })}
            onSelect={() => void run(async () => updateGroup(await taskGroupsApi.select(token, pane.group.id, pane.slot)))} />)}
        </div></div>
      </>}
    </section>}
    <Dialog open={Boolean(forward)} onOpenChange={open => { if (!open && !pending) setForward(null) }}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader><DialogTitle>{t("forward")}</DialogTitle><DialogDescription>{t("forwardDescription")}</DialogDescription></DialogHeader>
        <Label className="grid gap-2">{t("handoffAgent")}<NativeSelect aria-label={t("handoffAgent")} disabled={pending} value={forwardTarget} onChange={e => setForwardTarget(e.target.value)}>
          <NativeSelectOption value="">{t("chooseAgents")}</NativeSelectOption>{available.map(r => <NativeSelectOption key={r.runtimeId} value={r.runtimeId}>{r.name || r.displayName} · {r.runtimeType}</NativeSelectOption>)}
        </NativeSelect></Label>
        <details><summary className="cursor-pointer text-sm">{t("conclusion")}</summary><p className="max-h-48 overflow-auto whitespace-pre-wrap text-sm">{forward?.conclusion}</p></details>
        <Label className="grid gap-2">{t("forwardInstructions")}<Textarea aria-label={t("forwardInstructions")} value={instructions} maxLength={8000} disabled={pending} placeholder={t("forwardExample")} onChange={e => setInstructions(e.target.value)} /></Label>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter><Button variant="outline" disabled={pending} onClick={() => setForward(null)}>{t("cancel")}</Button><Button disabled={pending || !forwardTarget || !instructions.trim()} onClick={() => void run(sendForward)}>{t("sendForward")}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
}
