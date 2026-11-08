"use client"

import * as React from "react"
import { useTranslations } from "next-intl"
import { useWorkspace } from "@/components/workspace-context"
import { isApiError } from "@/lib/api/errors"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  id: string
  name: string
  project?: boolean
}

export function HistoryDeleteDialog({ open, onOpenChange, id, name, project = false }: Props) {
  const t = useTranslations("dashboard.historyDelete")
  const common = useTranslations("common")
  const { deleteProject, deleteSession, projectDeletionCount } = useWorkspace()
  const [count, setCount] = React.useState<number | null>(null)
  const [confirmation, setConfirmation] = React.useState("")
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [revision, setRevision] = React.useState(0)
  const submitting = React.useRef(false)

  React.useEffect(() => {
    if (!open) return
    let cancelled = false
    setError(null)
    setCount(null)
    setConfirmation("")
    if (project) {
      void projectDeletionCount(id).then((value) => {
        if (!cancelled) setCount(value)
      }).catch(() => {
        if (!cancelled) setError(t("previewFailed"))
      })
    }
    return () => { cancelled = true }
  }, [open, id, project, projectDeletionCount, revision, t])

  const submit = async () => {
    if (submitting.current || (project && (count === null || confirmation !== name))) return
    submitting.current = true
    setPending(true)
    setError(null)
    try {
      if (project) {
        if (!await deleteProject(id, count!)) return
      } else {
        await deleteSession(id)
      }
      onOpenChange(false)
    } catch (cause) {
      if (isApiError(cause) && cause.code === "session_running") {
        const payload = cause.payload as { detail?: { sessionIds?: unknown } } | undefined
        const ids = payload?.detail?.sessionIds
        const blocked = Array.isArray(ids) ? ids.filter((value): value is string => typeof value === "string").join(", ") : ""
        setError(t("running") + (blocked ? ` (${blocked})` : ""))
      } else if (isApiError(cause) && cause.code === "deletion_count_changed") {
        setCount(null)
        setConfirmation("")
        setError(t("countChanged"))
      } else {
        setError(t("failed"))
      }
    } finally {
      submitting.current = false
      setPending(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={(value) => { if (!pending) onOpenChange(value) }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{project ? t("projectTitle") : t("sessionTitle")}</AlertDialogTitle>
          <AlertDialogDescription>
            {project ? (count === null ? t("loading") : t("projectDescription", { name, count })) : t("sessionDescription", { name })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {project && <Input
          aria-label={t("confirmName")}
          placeholder={name}
          value={confirmation}
          onChange={(event) => setConfirmation(event.currentTarget.value)}
          disabled={pending || count === null}
          autoComplete="off"
        />}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{common("cancel")}</AlertDialogCancel>
          {project && count === null && error && <Button variant="outline" onClick={() => setRevision((value) => value + 1)}>{t("reload")}</Button>}
          <Button variant="destructive" onClick={() => void submit()} disabled={pending || (project && (count === null || confirmation !== name))}>
            {pending ? t("deleting") : t("confirm")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
