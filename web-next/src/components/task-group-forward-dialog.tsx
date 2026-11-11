"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { TaskGroupAgentSelect } from "@/components/task-group-agent-select"
import { AttachmentButton, AttachmentPreviewList, useAttachments, type AttachedFile } from "@/components/attachment-input"
import type { DeviceRuntimeView } from "@/features/dashboard/types"
import type { CandidateTarget } from "@/features/task-groups/api"

export function TaskGroupForwardDialog({ token, connectorId, sessionId, runtimes, initialRuntimeId, initialInstructions = "", initialAttachments = [], conclusion, pending, error, onClose, onSend }: {
  token: string; connectorId: string; sessionId: string; runtimes: DeviceRuntimeView[]
  initialRuntimeId?: string; initialInstructions?: string; initialAttachments?: AttachedFile[]; conclusion?: string
  pending: boolean; error: string; onClose: () => void
  onSend: (targets: CandidateTarget[], instructions: string, attachments: { fileId: string }[]) => Promise<void>
}) {
  const [slots, setSlots] = React.useState([0])
  const nextSlot = React.useRef(1)
  const [targets, setTargets] = React.useState<Record<number, CandidateTarget | null>>({})
  const callbacks = React.useRef(new Map<number, (target: CandidateTarget | null) => void>())
  const onTarget = (slot: number) => {
    if (!callbacks.current.has(slot)) callbacks.current.set(slot, target => setTargets(rows => ({ ...rows, [slot]: target })))
    return callbacks.current.get(slot)!
  }
  const [instructions, setInstructions] = React.useState(initialInstructions)
  const files = useAttachments({ sessionId, token, initialAttachments })
  const selected = slots.flatMap(slot => targets[slot] ? [targets[slot]!] : [])
  const duplicate = new Set(selected.map(target => target.runtimeId)).size !== selected.length
  const uploading = files.attachments.some(file => !file.uploaded)
  return <Dialog open onOpenChange={open => { if (!open && !pending) onClose() }}>
    <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
      <DialogHeader><DialogTitle>转发给其他 AI</DialogTitle><DialogDescription>选择 1～3 个目标 AI，在当前项目下分别创建新会话；携带原始任务、近期对话、历史附件及可用的代码快照，也可补充新附件。</DialogDescription></DialogHeader>
      {!runtimes.length && <p role="status">暂无可用 AI，请检查设备连接。</p>}
      {slots.map((slot, index) => <div key={slot} className="space-y-2 rounded-md border p-3">
        <TaskGroupAgentSelect token={token} connectorId={connectorId} runtimes={runtimes} initialRuntimeId={index === 0 ? initialRuntimeId : runtimes.find(row => !selected.some(target => target.runtimeId === row.runtimeId))?.runtimeId} label={`目标 AI ${index + 1}`} disabled={pending} onChange={onTarget(slot)} />
        {slots.length > 1 && <Button variant="ghost" size="sm" disabled={pending} onClick={() => setSlots(rows => rows.filter(row => row !== slot))}>移除目标</Button>}
      </div>)}
      <Button variant="outline" disabled={pending || slots.length >= Math.min(3, runtimes.length)} onClick={() => setSlots(rows => [...rows, nextSlot.current++])}>添加目标 AI</Button>
      {duplicate && <p role="alert">请为每个目标选择不同的 AI。</p>}
      {conclusion && <details><summary>来源结论</summary><p className="max-h-48 overflow-auto whitespace-pre-wrap text-sm">{conclusion}</p></details>}
      <label className="grid gap-2 text-sm">补充指令<Textarea aria-label="补充指令" maxLength={8000} value={instructions} disabled={pending} onChange={e => setInstructions(e.target.value)} /></label>
      <AttachmentPreviewList attachments={files.attachments} onRemove={id => { if (!pending) files.remove(id) }} />
      <AttachmentButton attachments={files.attachments} onAttach={files.add} isDragging={false} disabled={pending} />
      {files.attachmentError && <p role="alert" className="text-sm text-destructive">{files.attachmentError}</p>}
      {uploading && <p role="status">请等待附件上传完成；上传失败的附件请移除后重新添加。</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button variant="outline" disabled={pending} onClick={onClose}>取消</Button>
      <Button disabled={pending || selected.length !== slots.length || duplicate || !instructions.trim() || uploading} onClick={() => void onSend(selected, instructions.trim(), files.attachments.map(file => ({ fileId: file.uploaded!.fileId })))}>{pending ? "正在转发…" : "发送"}</Button>
    </DialogContent>
  </Dialog>
}
