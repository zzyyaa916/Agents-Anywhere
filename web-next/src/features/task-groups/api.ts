import { apiClient } from "@/lib/api"

export type CandidateTarget = { runtime: string; runtimeId: string; selections: Record<string, string | null> }
export type TaskGroup = {
  id: string; projectId: string; createdAt: string; phase: "preparing" | "ready"; selected: number | null
  base?: string; paths?: string[]; handoffBrief?: string
  request: { content: string; candidates: CandidateTarget[]; source?: { groupId: string; slot: number; mode: string } }
  candidates: { phase: "pending" | "dispatching" | "sent" | "unknown"; sessionId: string | null; status?: string; error?: string }[]
}
export type CandidateDiff = { base: string; head: string; stat: string; diff: string }
const path = (id: string) => `/task-groups/${encodeURIComponent(id)}`
export const taskGroupsApi = {
  list: (token: string, projectId: string) => apiClient.get<{ groups: TaskGroup[] }>("/task-groups", { token, query: { projectId } }),
  get: (token: string, id: string) => apiClient.get<TaskGroup>(path(id), { token }),
  create: (token: string, body: { operationId: string; projectId: string; content: string; candidates: CandidateTarget[] }) => apiClient.post<TaskGroup>("/task-groups", body, { token }),
  start: (token: string, id: string, slot: number) => apiClient.post<TaskGroup>(`${path(id)}/candidates/${slot}/start`, {}, { token }),
  diff: (token: string, id: string, slot: number) => apiClient.get<CandidateDiff>(`${path(id)}/candidates/${slot}/diff`, { token }),
  select: (token: string, id: string, slot: number) => apiClient.post<TaskGroup>(`${path(id)}/select`, { slot }, { token }),
  handoff: (token: string, id: string, body: { operationId: string; slot: number; mode: "review" | "continue"; target: CandidateTarget }) => apiClient.post<TaskGroup>(`${path(id)}/handoffs`, body, { token }),
}

export function candidateStopped(candidate: TaskGroup["candidates"][number]) {
  return candidate.phase === "sent" && ["idle", "error", "limited"].includes(candidate.status ?? "")
}
