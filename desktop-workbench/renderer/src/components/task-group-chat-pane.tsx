"use client"

import * as React from "react"
import type { AttachedFile } from "@/components/attachment-input"
import { Forward, Maximize2, Minimize2, X } from "lucide-react"
import { useTranslations } from "next-intl"
import { Button } from "@/components/ui/button"
import { SessionDetail, type SessionMemorySnapshot } from "@/components/session-detail"
import { useWorkspace } from "@/components/workspace-context"
import { messageText } from "@/components/session/session-utils"
import { candidateStopped, type CandidateDiff, type TaskGroup } from "@/features/task-groups/api"

export type ChatPaneMode = "open" | "minimized" | "closed"

export function TaskGroupChatPane({ group, slot, title, token, mode, pending, diff, onModeChange, onForward, onInspect, onSelect, onQueueReady, onForwardCommand }: {
  group: TaskGroup; slot: number; title: string; token: string; mode: ChatPaneMode; pending: boolean; diff?: CandidateDiff
  onForwardCommand?: (text: string, attachments: AttachedFile[]) => Promise<boolean | null>
  onQueueReady?: (enqueue: ((text: string) => boolean) | null) => void
  onModeChange: (mode: ChatPaneMode) => void
  onForward: (conclusion: string) => void
  onInspect: () => void
  onSelect: () => void
}) {
  const t = useTranslations("taskGroups")
  const { upsertSession, reportSessionStreamProgress, projects, connectors } = useWorkspace()
  const [conclusion, setConclusion] = React.useState("")
  const snapshot = React.useCallback((value: SessionMemorySnapshot | null) => {
    const last = value?.items.filter(item => item.type === "message" && item.role === "assistant").at(-1)
    setConclusion(last ? messageText(last) : "")
  }, [])
  const candidate = group.candidates[slot]
  if (!candidate) return null
  const connectorId = projects.find(project => project.id === group.projectId)?.connectorId
  const deviceOs = connectors.find(connector => connector.id === connectorId)?.deviceOs
  const stopped = candidateStopped(candidate)
  const minimized = mode === "minimized"
  return <article data-pane-key={`${group.id}:${slot}`} data-session-id={candidate.sessionId ?? ""} aria-label={title}
    className={`${mode === "closed" ? "hidden" : "flex"} min-w-0 flex-col overflow-hidden rounded-lg border bg-background ${minimized ? "" : "h-[60dvh] min-h-80"}`}>
    <header className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
      <div className="min-w-0">
        <h3 className="truncate text-sm font-medium" title={title}>{title}{group.selected === slot ? ` · ${t("selected")}` : ""}</h3>
        <p className="text-xs text-muted-foreground">{candidate.status ? t(`status.${candidate.status}`) : t(`phase.${candidate.phase}`)}</p>
      </div>
      <div className="flex shrink-0 gap-1">
        <Button variant="ghost" size="icon-sm" aria-label={t("forward")} title={t("forward")} disabled={pending || !stopped || !conclusion.trim()} onClick={() => onForward(conclusion)}><Forward /></Button>
        <Button variant="ghost" size="icon-sm" aria-label={t(minimized ? "restore" : "minimize")} title={t(minimized ? "restore" : "minimize")} onClick={() => onModeChange(minimized ? "open" : "minimized")}>{minimized ? <Maximize2 /> : <Minimize2 />}</Button>
        <Button variant="ghost" size="icon-sm" aria-label={t("close")} title={t("close")} onClick={() => onModeChange("closed")}><X /></Button>
      </div>
    </header>
    <div className={minimized ? "hidden" : "flex min-h-0 flex-1 flex-col"}>
      {candidate.error && <p role="alert" className="px-3 py-2 text-xs text-destructive">{candidate.error}</p>}
      <div className="min-h-0 flex-1 overflow-hidden">
        {candidate.sessionId ? <SessionDetail key={candidate.sessionId} token={token} sessionId={candidate.sessionId}
          onForwardCommand={onForwardCommand} onQueueReady={onQueueReady} fallbackSession={null} connectorDeviceOs={deviceOs} onSessionUpdated={upsertSession}
          onStreamProgress={reportSessionStreamProgress} onMemorySnapshotUpdated={snapshot} />
          : <p className="p-4 text-sm text-muted-foreground">{t("waitingForSession")}</p>}
      </div>
      <footer className="shrink-0 space-y-2 border-t p-2">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={pending || !stopped} onClick={onInspect}>{t("inspect")}</Button>
          <Button variant="outline" size="sm" disabled={pending || !stopped} onClick={onSelect}>{t("select")}</Button>
        </div>
        {diff && <details><summary className="cursor-pointer text-sm">{t("diff")}</summary><pre className="max-h-48 overflow-auto whitespace-pre-wrap text-xs">{diff.stat}{"\n"}{diff.diff || t("noChanges")}</pre></details>}
      </footer>
    </div>
  </article>
}
