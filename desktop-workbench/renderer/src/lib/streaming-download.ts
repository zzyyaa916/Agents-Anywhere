import { toast } from "sonner"
import { getDesktopWorkbenchBridge, type DesktopDownloadResult } from "@/features/desktop/bridge"

export type PreparedDownload = { downloadUrl: string; size?: number | null }

export type StreamingDownloadTexts = {
  preparing: string
  progress: (values: { percent: number | null; received: string; total: string | null }) => string
  cancel: string
  canceled: string
  done: (name: string) => string
  showInFolder: string
  expired: string
}

export type StreamingDownloadOutcome =
  | { status: "unsupported" }
  | { status: "canceled" }
  | { status: "done" }
  | { status: "error"; message: string }

/** Whether Main can stream a save-as download to disk (packaged Desktop). */
export function canStreamDownloads(): boolean {
  return Boolean(getDesktopWorkbenchBridge()?.downloads)
}

/**
 * Save a Connector file through Main without buffering it in the renderer.
 *
 * The save dialog opens first and needs only the name. The transfer is prepared
 * only after a destination is chosen, because a prepared transfer is short-lived;
 * an expired one is prepared again once. Errors are returned so callers can show
 * them in their existing style; progress, cancel and completion use a toast.
 */
export async function streamDownloadToDisk(input: {
  name: string
  authToken: string | null
  prepare: () => Promise<PreparedDownload>
  texts: StreamingDownloadTexts
}): Promise<StreamingDownloadOutcome> {
  const downloads = getDesktopWorkbenchBridge()?.downloads
  if (!downloads) return { status: "unsupported" }
  const target = await downloads.chooseTarget(input.name)
  if (target.canceled) return { status: "canceled" }

  const { id } = target
  const toastId = `download-${id}`
  const { texts } = input
  let canceledByUser = false
  const cancelAction = {
    label: texts.cancel,
    onClick: () => {
      canceledByUser = true
      void downloads.cancel(id)
    },
  }
  toast.loading(texts.preparing, { id: toastId, action: cancelAction, duration: Infinity })
  const unsubscribe = downloads.onProgress((progress) => {
    if (progress.id !== id || canceledByUser) return
    const percent = progress.total ? Math.min(100, Math.floor((progress.received * 100) / progress.total)) : null
    toast.loading(texts.progress({
      percent,
      received: formatBytes(progress.received),
      total: progress.total === null ? null : formatBytes(progress.total),
    }), { id: toastId, action: cancelAction, duration: Infinity })
  })

  try {
    let result: DesktopDownloadResult | null = null
    for (let attempt = 0; attempt < 2; attempt++) {
      let prepared: PreparedDownload
      try {
        prepared = await input.prepare()
      } catch (error) {
        void downloads.cancel(id)
        if (canceledByUser) return finishCanceled(toastId, texts)
        toast.dismiss(toastId)
        return { status: "error", message: error instanceof Error ? error.message : String(error) }
      }
      if (canceledByUser) {
        void downloads.cancel(id)
        return finishCanceled(toastId, texts)
      }
      result = await downloads.start({ id, url: prepared.downloadUrl, authToken: input.authToken, size: prepared.size ?? null })
      if (result.ok || result.code !== "expired" || attempt > 0) break
    }
    if (result?.ok) {
      toast.success(texts.done(result.fileName), {
        id: toastId,
        duration: 8000,
        action: { label: texts.showInFolder, onClick: () => void downloads.showInFolder(id) },
      })
      return { status: "done" }
    }
    if (canceledByUser || result?.code === "canceled") return finishCanceled(toastId, texts)
    void downloads.cancel(id)
    toast.dismiss(toastId)
    return { status: "error", message: result?.code === "expired" ? texts.expired : result?.message ?? "" }
  } finally {
    unsubscribe()
  }
}

function finishCanceled(toastId: string, texts: StreamingDownloadTexts): StreamingDownloadOutcome {
  toast(texts.canceled, { id: toastId, duration: 4000 })
  return { status: "canceled" }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB", "TB"]
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`
}

/** Texts from the `dashboard.panels.files` translations. */
export function filesDownloadTexts(t: (key: string, values?: Record<string, string | number>) => string): StreamingDownloadTexts {
  return {
    preparing: t("downloadPreparing"),
    progress: ({ percent, received, total }) => percent === null || total === null
      ? t("downloadProgressUnknown", { received })
      : t("downloadProgress", { percent, received, total }),
    cancel: t("downloadCancel"),
    canceled: t("downloadCanceled"),
    done: (name) => t("downloadDone", { name }),
    showInFolder: t("downloadShowInFolder"),
    expired: t("downloadExpired"),
  }
}
