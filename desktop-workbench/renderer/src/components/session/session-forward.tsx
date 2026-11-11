"use client"

import * as React from "react"
import { Forward } from "lucide-react"
import { Button } from "@/components/ui/button"
import { TaskGroupForwardDialog } from "@/components/task-group-forward-dialog"
import { useWorkspace } from "@/components/workspace-context"
import { dashboardApi } from "@/features/dashboard/api"
import type { DeviceRuntimeView, SessionView } from "@/features/dashboard/types"
import { taskGroupsApi, type CandidateTarget } from "@/features/task-groups/api"
import { forwardToTargets } from "@/features/task-groups/forward-to-targets"
import { parseForwardCommand } from "@/features/task-groups/forward-command"
import type { AttachedFile } from "@/components/session/session-composer"

type ForwardSource = Pick<SessionView, "id" | "connectorId" | "status">
export function useSessionForward(token: string, session: ForwardSource | null | undefined, enabled: boolean) {
  const { openSession, refreshData } = useWorkspace()
  const [draft, setDraft] = React.useState<{ name: string; instructions: string; attachments: AttachedFile[] } | null>(null)
  const [runtimes, setRuntimes] = React.useState<DeviceRuntimeView[]>([])
  const [loaded, setLoaded] = React.useState(false)
  const [error, setError] = React.useState("")
  const [pending, setPending] = React.useState(false)
  const operations = React.useRef(new Map<string, string>())
  const generation = React.useRef(0)
  React.useEffect(() => { setDraft(null); operations.current.clear(); ++generation.current; setPending(false) }, [session?.id])
  React.useEffect(() => {
    if (!draft || !session) return
    let cancelled = false
    setRuntimes([]); setLoaded(false)
    void dashboardApi.getConnectorRuntimes(token, session.connectorId).then(result => {
      if (!cancelled) { setRuntimes(result.runtimes.filter(row => row.status === "running")); setLoaded(true) }
    }).catch(e => { if (!cancelled) setError(String(e.message ?? e)) })
    return () => { cancelled = true }
  }, [Boolean(draft), token, session?.connectorId])
  const begin = (name = "", instructions = "请审核当前任务结果，指出问题及后续建议。", attachments: AttachedFile[] = []) => {
    setError(""); setDraft({ name, instructions, attachments })
  }
  const handleCommand = async (text: string, files: AttachedFile[]): Promise<boolean | null> => {
    if (!enabled) return null
    const command = parseForwardCommand(text)
    if (!command) return null
    begin(command.target, command.instructions, files)
    return false
  }
  const send = async (targets: CandidateTarget[], instructions: string, attachments: { fileId: string }[]) => {
    if (!session || pending) return
    const turn = generation.current
    setPending(true); setError("")
    try {
      const groups = await forwardToTargets({ token, source: session.id, targets, instructions, attachments, operations: operations.current,
        create: (target, operationId) => taskGroupsApi.handoffSession(token, session.id, { operationId, slot: 0, mode: "continue", target, instructions, attachments }),
        onUpdate: () => {},
      })
      await refreshData()
      if (turn !== generation.current) return
      setDraft(null)
      const id = groups[0]?.candidates[0]?.sessionId
      if (id) openSession(id)
    } catch (e) {
      await Promise.resolve().then(() => refreshData()).catch(() => {})
      if (turn === generation.current) setError(e instanceof Error ? e.message : String(e))
    } finally { if (turn === generation.current) setPending(false) }
  }
  const available = session && ["idle", "error", "limited"].includes(session.status)
  return { handleCommand, control: enabled && session ? <>
    <Button variant="ghost" size="sm" disabled={!available} title={available ? "转发到其他 AI，保留原项目" : "请等待当前 AI 完成"} onClick={() => begin()}><Forward className="size-4" />转发给其他 AI</Button>
    {draft && (loaded ? <TaskGroupForwardDialog token={token} connectorId={session.connectorId} sessionId={session.id} runtimes={runtimes}
      initialRuntimeId={runtimes.find(row => [row.name, row.displayName, row.runtimeId, row.runtimeType].some(name => name?.toLowerCase() === draft.name.toLowerCase()))?.runtimeId}
      initialInstructions={draft.instructions} initialAttachments={draft.attachments} pending={pending} error={error} onClose={() => setDraft(null)} onSend={send} />
      : <div role={error ? "alert" : "status"}>{error || "正在读取可用 AI…"}<Button variant="ghost" onClick={() => setDraft(null)}>取消</Button></div>)}
  </> : null }
}
