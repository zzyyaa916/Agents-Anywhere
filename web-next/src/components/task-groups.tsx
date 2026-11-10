"use client"

import * as React from "react"
import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { useAuth } from "@/components/auth/auth-context"
import { useWorkspace } from "@/components/workspace-context"
import { createClientId } from "@/lib/id"
import { candidateStopped, taskGroupsApi, type TaskGroup, type CandidateDiff, type CandidateTarget } from "@/features/task-groups/api"
import { dashboardApi } from "@/features/dashboard/api"

const operationId = () => createClientId("group").replaceAll("_", "-")

export function TaskGroupsButton() {
  const [open, setOpen] = React.useState(false)
  const t = useTranslations("taskGroups")
  return <><Button variant="outline" size="sm" onClick={() => setOpen(true)}>{t("entry")}</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader><DialogTitle>{t("title")}</DialogTitle><DialogDescription>{t("description")}</DialogDescription></DialogHeader>
        {open && <TaskGroupsWorkbench />}
      </DialogContent>
    </Dialog></>
}

function TaskGroupsWorkbench() {
  const t = useTranslations("taskGroups")
  const { session } = useAuth()
  const { projects, runtimes, newSessionProject, openSession, refreshData } = useWorkspace()
  const token = session?.accessToken ?? ""
  const [projectId, setProjectId] = React.useState(newSessionProject?.id ?? projects[0]?.id ?? "")
  const [content, setContent] = React.useState("")
  const [count, setCount] = React.useState(3)
  const [targets, setTargets] = React.useState<string[]>(["", "", ""])
  const [groups, setGroups] = React.useState<TaskGroup[]>([])
  const [current, setCurrent] = React.useState<TaskGroup | null>(null)
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState("")
  const [diffs, setDiffs] = React.useState<Record<number, CandidateDiff>>({})
  const [summaries, setSummaries] = React.useState<Record<number, string>>({})
  const [handoffTarget, setHandoffTarget] = React.useState("")
  const [mode, setMode] = React.useState<"review" | "continue">("review")
  const identity = React.useRef({ signature: "", id: "" })
  const handoffIdentity = React.useRef({ signature: "", id: "" })
  const project = projects.find(p => p.id === projectId)
  const available = runtimes.filter(r => r.connectorId === project?.connectorId && r.status === "running")
  const generation = React.useRef(0)

  React.useEffect(() => {
    const turn = ++generation.current
    setCurrent(null); setDiffs({}); setSummaries({}); setGroups([]); setError(""); setPending(false)
    if (projectId && token) void taskGroupsApi.list(token, projectId).then(result => {
      if (turn === generation.current) setGroups(result.groups)
    }).catch(e => { if (turn === generation.current) setError(String(e.message ?? e)) })
    return () => { ++generation.current }
  }, [projectId, token])

  React.useEffect(() => {
    if (!current || !token) return
    let disposed = false
    const id = current.id
    const timer = window.setInterval(() => {
      void taskGroupsApi.get(token, id).then(row => { if (!disposed) setCurrent(row) }).catch(() => undefined)
    }, 5000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [current?.id, token])

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

  function show(group: TaskGroup) {
    setCurrent(group); setDiffs({}); setSummaries({})
    setGroups(rows => [group, ...rows.filter(row => row.id !== group.id)])
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

  async function inspect(slot: number) {
    if (!current) return
    const groupId = current.id
    const turn = generation.current
    const candidate = current.candidates[slot]
    if (!candidate) return
    const [diff, timeline] = await Promise.all([
      taskGroupsApi.diff(token, groupId, slot),
      candidate.sessionId ? dashboardApi.getLatestSessionTimeline(token, candidate.sessionId, 30) : Promise.resolve(null),
    ])
    if (turn !== generation.current) return
    setDiffs(rows => ({ ...rows, [slot]: diff }))
    const messages = timeline?.items.filter(item => item.type === "message" && item.role === "assistant") ?? []
    const last = messages.at(-1)?.content
    setSummaries(rows => ({ ...rows, [slot]: typeof last?.text === "string" ? last.text : "" }))
  }

  const runtimeOptions = <><NativeSelectOption value="">{t("defaultAgent")}</NativeSelectOption>{available.map(r => <NativeSelectOption key={r.runtimeId} value={r.runtimeId}>{r.name || r.displayName} · {r.runtimeType}</NativeSelectOption>)}</>
  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-2">
      <Label className="grid gap-2">{t("project")}<NativeSelect aria-label={t("project")} value={projectId} disabled={pending} onChange={e => setProjectId(e.target.value)}>
        {projects.map(p => <NativeSelectOption key={p.id} value={p.id}>{p.name}</NativeSelectOption>)}
      </NativeSelect></Label>
      <Label className="grid gap-2">{t("execution")}<NativeSelect value={count} disabled={pending} onChange={e => setCount(Number(e.target.value))}>
        <NativeSelectOption value="1">{t("single")}</NativeSelectOption><NativeSelectOption value="3">{t("three")}</NativeSelectOption>
      </NativeSelect></Label>
    </div>
    <Textarea aria-label={t("task")} value={content} disabled={pending} onChange={e => setContent(e.target.value)} placeholder={t("task")} />
    <div className="grid gap-3 sm:grid-cols-3">{Array.from({ length: count }, (_, slot) => <Label key={slot} className="grid gap-2">{t("candidate", { n: slot + 1 })}
      <NativeSelect aria-label={t("candidate", { n: slot + 1 })} disabled={pending} value={targets[slot]} onChange={e => setTargets(rows => rows.map((value, n) => n === slot ? e.target.value : value))}>{runtimeOptions}</NativeSelect>
    </Label>)}</div>
    <p className="text-sm text-muted-foreground">{t("limits")}</p>
    <Button disabled={pending || !projectId || !content.trim() || !available.length} onClick={() => void run(create)}>{t("prepare")}</Button>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Label className="grid gap-2">{t("history")}<NativeSelect disabled={pending} value={current?.id ?? ""} onChange={e => {
      const row = groups.find(g => g.id === e.target.value)
      if (row) void run(async () => show(await taskGroupsApi.get(token, row.id)))
    }}><NativeSelectOption value="">{t("chooseGroup")}</NativeSelectOption>{groups.map(g => <NativeSelectOption key={g.id} value={g.id}>{g.request.content.slice(0, 70)}</NativeSelectOption>)}</NativeSelect></Label>
    {current && <section className="space-y-4 border-t pt-4">
      <p className="whitespace-pre-wrap text-sm">{current.request.content}</p>
      <p className="break-all text-xs text-muted-foreground">{t("base")}: {current.base ?? t("preparing")}</p>
      {current.handoffBrief && <details><summary className="cursor-pointer text-sm">{t("handoffPreview")}</summary><pre className="max-h-60 overflow-auto whitespace-pre-wrap text-xs">{current.handoffBrief}</pre></details>}
      <Button disabled={pending || current.phase !== "ready" || !current.candidates.some(c => c.phase === "pending")} onClick={() => void run(async () => {
        const id = current.id
        const turn = generation.current
        const results = await Promise.allSettled(current.candidates.map((candidate, slot) => candidate.phase === "pending" ? taskGroupsApi.start(token, id, slot) : Promise.resolve(null)))
        if (turn !== generation.current) return
        show(await taskGroupsApi.get(token, id)); await refreshData()
        if (results.some(r => r.status === "rejected")) throw new Error(t("checkBeforeRetry"))
      })}>{t("start")}</Button>
      <div className="grid gap-3 lg:grid-cols-3">{current.candidates.map((candidate, slot) => <article key={slot} className="space-y-3 rounded-lg border p-3">
        <h3 className="font-medium">{t("candidate", { n: slot + 1 })}{current.selected === slot ? ` · ${t("selected")}` : ""}</h3>
        <p className="text-xs">{current.request.candidates[slot]?.runtime} · {candidate.status ? t(`status.${candidate.status}`) : t(`phase.${candidate.phase}`)}</p>
        {candidate.error && <p role="alert" className="text-xs text-destructive">{candidate.error}</p>}
        {candidate.sessionId && <Button variant="outline" size="sm" onClick={() => openSession(candidate.sessionId!)}>{t("openSession")}</Button>}
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={pending || !candidateStopped(candidate)} onClick={() => void run(() => inspect(slot))}>{t("inspect")}</Button>
          <Button variant="outline" size="sm" disabled={pending || !candidateStopped(candidate)} onClick={() => void run(async () => setCurrent(await taskGroupsApi.select(token, current.id, slot)))}>{t("select")}</Button>
        </div>
        {summaries[slot] && <p className="max-h-60 overflow-auto whitespace-pre-wrap text-sm">{summaries[slot]}</p>}
        {diffs[slot] && <details open><summary className="cursor-pointer text-sm">{t("diff")}</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">{diffs[slot].stat}{"\n"}{diffs[slot].diff || t("noChanges")}</pre></details>}
      </article>)}</div>
      <div className="flex flex-wrap items-end gap-3 border-t pt-4">
        <Label className="grid gap-2">{t("handoffAgent")}<NativeSelect disabled={pending} value={handoffTarget} onChange={e => setHandoffTarget(e.target.value)}>{runtimeOptions}</NativeSelect></Label>
        <Label className="grid gap-2">{t("handoffMode")}<NativeSelect disabled={pending} value={mode} onChange={e => setMode(e.target.value as "review" | "continue")}><NativeSelectOption value="review">{t("review")}</NativeSelectOption><NativeSelectOption value="continue">{t("continue")}</NativeSelectOption></NativeSelect></Label>
        <Button disabled={pending || current.selected === null || !available.length} onClick={() => void run(async () => {
          if (current.selected === null) return
          const body = { slot: current.selected, mode, target: target(handoffTarget || available[0]?.runtimeId || "") }
          const signature = JSON.stringify([current.id, body])
          if (handoffIdentity.current.signature !== signature) handoffIdentity.current = { signature, id: operationId() }
          show(await taskGroupsApi.handoff(token, current.id, { ...body, operationId: handoffIdentity.current.id }))
        })}>{t("prepareHandoff")}</Button>
      </div>
      <p className="text-xs text-muted-foreground">{t("handoffLimits")}</p>
    </section>}
  </div>
}
