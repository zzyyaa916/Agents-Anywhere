"use client"

import * as React from "react"
import { useTranslations } from "next-intl"
import { useAuth } from "@/components/auth/auth-context"
import { useAccountUsage } from "@/components/account-usage"
import { Button } from "@/components/ui/button"
import type { ChannelRuntimeState, DeviceRuntimeView } from "@/features/dashboard/types"
import { dashboardApi } from "@/features/dashboard/api"
import { accountReadiness, channelReadiness } from "@/features/dashboard/runtime-readiness"
import { modelConfigApi } from "@/features/model-config/api"
import { errorMessage } from "@/lib/api/errors"

export function RuntimeReadiness({ runtime, channel, onChanged }: {
  runtime: DeviceRuntimeView
  channel?: ChannelRuntimeState
  onChanged: () => void | Promise<void>
}) {
  const t = useTranslations("dashboard.device.readiness")
  const { session } = useAuth()
  const { data } = useAccountUsage()
  const key = [session?.accessToken, runtime.connectorId, runtime.runtimeId, runtime.updatedAt, channel?.updatedAt].join(":")
  const active = React.useRef(key)
  active.current = key
  const [busy, setBusy] = React.useState<string | null>(null)
  const [saved, setSaved] = React.useState<{ key: string; count?: number; error?: string } | null>(null)
  const result = saved?.key === key ? saved : null
  const account = data?.snapshots.find(s => s.bindings.some(b => b.connectorId === runtime.connectorId && b.runtimeId === runtime.runtimeId))
  const state = channelReadiness(channel)
  const check = async () => {
    if (!session || busy === key) return
    setBusy(key)
    try {
      if (state === "channelFailed") {
        await modelConfigApi.retryChannel(session.accessToken, runtime)
        await onChanged()
      }
      const response = await dashboardApi.getConnectorRuntimeModelCatalog(session.accessToken, runtime.connectorId, runtime.runtimeId)
      if (active.current === key) setSaved({ key, count: response.catalog.models.length })
    } catch (error) {
      if (active.current === key) setSaved({ key, error: errorMessage(error) })
    } finally {
      setBusy(previous => previous === key ? null : previous)
    }
  }
  if (runtime.status !== "running") return null
  return <div className="mt-1 space-y-1 text-xs text-muted-foreground" title={t("hint")}>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className={state === "channelFailed" ? "text-destructive" : undefined}>{t(state)}</span>
      <span>{t(accountReadiness(account))}</span>
      <span>{result?.count !== undefined ? t("modelsReady", { count: result.count }) : t(result?.error ? "modelsFailed" : "modelsUnknown")}</span>
      <Button variant="link" size="sm" className="h-auto p-0 text-xs" disabled={busy === key} onClick={() => void check()}>
        {t(busy === key ? "checking" : state === "channelFailed" ? "retryChannel" : "check")}
      </Button>
    </div>
    {result?.error && <p role="alert" className="break-words text-destructive">{result.error}</p>}
  </div>
}
