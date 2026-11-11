import { readConversationState, writeConversationState } from "./conversation-storage"
import { createClientId } from "@/lib/id"
import { taskGroupsApi, type CandidateTarget, type TaskGroup } from "./api"

// Keep each recipient's identity across partial failures so retrying cannot replay a paid turn.
export async function forwardToTargets({ token, source, targets, instructions, attachments, operations, operationScope, create, onUpdate }: {
  token: string; source: string; targets: CandidateTarget[]; instructions: string; attachments: { fileId: string }[]
  operations: Map<string, string>; operationScope?: string
  create: (target: CandidateTarget, operationId: string) => Promise<TaskGroup>
  onUpdate: (group: TaskGroup) => void
}) {
  const saved = operationScope ? readConversationState(operationScope) : {}
  const signatures: string[] = []
  const completed: TaskGroup[] = []
  const errors: string[] = []
  for (const target of targets) {
    const signature = JSON.stringify([source, target, instructions, attachments])
    signatures.push(signature)
    if (!operations.has(signature)) operations.set(signature, typeof saved[signature] === "string" ? saved[signature] as string : createClientId("forward").replaceAll("_", "-"))
    saved[signature] = operations.get(signature)!
    if (operationScope && !writeConversationState(operationScope, saved)) throw new Error("无法保存转发状态，尚未发送，请检查本机存储后重试。")
    try {
      const prepared = await create(target, operations.get(signature)!)
      onUpdate(prepared)
      const started = await taskGroupsApi.start(token, prepared.id, 0)
      onUpdate(started)
      const candidate = started.candidates[0]
      if (!candidate || candidate.phase !== "sent" || !candidate.sessionId) throw new Error(candidate?.error || "发送结果尚未确认，请检查目标会话，避免重复发送。")
      completed.push(started)
    } catch (error) { errors.push(`${target.runtimeId}: ${error instanceof Error ? error.message : String(error)}`) }
  }
  if (errors.length) throw new Error(errors.join("\n"))
  for (const signature of signatures) { operations.delete(signature); delete saved[signature] }
  if (operationScope && !writeConversationState(operationScope, saved)) throw new Error("目标已接收，但本机无法保存完成状态，请先检查目标会话。")
  return completed
}
