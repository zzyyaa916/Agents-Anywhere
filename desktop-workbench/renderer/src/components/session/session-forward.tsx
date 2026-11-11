"use client"

import * as React from "react"
import { useAuth } from "@/components/auth/auth-context"
import { conversationServer, conversationScope } from "@/features/task-groups/conversation-storage"
import { toast } from "sonner"
import { resolveForwardTargets } from "@/features/task-groups/forward-targets"
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

type ForwardSource = Pick<SessionView, "id" | "connectorId" | "status"> & Partial<Pick<SessionView, "runtimeId" | "runtime">>
export function useSessionForward(token: string, session: ForwardSource | null | undefined, enabled: boolean, stayInWorkspace = false) {
  const { session: account } = useAuth()
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
    if (!enabled || !session) return null
    const command = parseForwardCommand(text)
    if (!command) return null
    try {
      if (files.some(file => !file.uploaded)) throw new Error("请等待附件上传完成。")
      const inventory = await dashboardApi.getConnectorRuntimes(token, session.connectorId)
      const targets = await resolveForwardTargets(token, session.connectorId, inventory.runtimes, command.targets)
      return await send(targets, command.instructions, files.map(file => ({ fileId: file.uploaded!.fileId })), true)
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)); return false }
  }
  const send = async (targets: CandidateTarget[], instructions: string, attachments: { fileId: string }[], notify = false) => {
    if (!session || pending) return false
    const turn = generation.current
    setPending(true); setError("")
    try {
      const groups = await forwardToTargets({ token, source: session.id, targets, instructions, attachments, operations: operations.current, operationScope: `${conversationScope(account?.userId ?? "", conversationServer(account))}:forward:${session.id}`,
        create: (target, operationId) => taskGroupsApi.handoffSession(token, session.id, { operationId, slot: 0, mode: "continue", target, instructions, attachments }),
        onUpdate: () => {},
      })
      await refreshData()
      if (turn !== generation.current) return false
      setDraft(null)
      const id = groups[0]?.candidates[0]?.sessionId
      if (id && !stayInWorkspace) openSession(id)
      return true
    } catch (e) {
      await Promise.resolve().then(() => refreshData()).catch(() => {})
      if (turn === generation.current) setError(e instanceof Error ? e.message : String(e))
      if (notify) toast.error(e instanceof Error ? e.message : String(e))
      return false
    } finally { if (turn === generation.current) setPending(false) }
  }
  const available = session && ["idle", "error", "limited"].includes(session.status)
  return { handleCommand, control: enabled && session ? <>
    <Button variant="ghost" size="icon-sm" aria-label="转发给其他 AI" disabled={!available} title={available ? "转发到其他 AI，保留原项目" : "请等待当前 AI 完成"} onClick={() => begin()}><Forward className="size-4" /></Button>
    {draft && (loaded ? <TaskGroupForwardDialog token={token} connectorId={session.connectorId} sessionId={session.id} runtimes={runtimes.filter(row => row.runtimeId !== (session.runtimeId ?? session.runtime))}
      initialRuntimeId={runtimes.find(row => [row.name, row.displayName, row.runtimeId, row.runtimeType].some(name => name?.toLowerCase() === draft.name.toLowerCase()))?.runtimeId}
      initialInstructions={draft.instructions} initialAttachments={draft.attachments} pending={pending} error={error} onClose={() => setDraft(null)} onSend={async (...args) => { await send(...args) }} />
      : <div role={error ? "alert" : "status"}>{error || "正在读取可用 AI…"}<Button variant="ghost" onClick={() => setDraft(null)}>取消</Button></div>)}
  </> : null }
}
