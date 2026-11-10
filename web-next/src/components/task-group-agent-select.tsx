"use client"

import * as React from "react"
import { useTranslations } from "next-intl"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { dashboardApi } from "@/features/dashboard/api"
import type { DeviceRuntimeView, ProtocolModelCatalog, ProtocolPermissionCatalog } from "@/features/dashboard/types"
import type { CandidateTarget } from "@/features/task-groups/api"
import { CAPABILITY, capabilityIsUsable, findCapability } from "@/components/session/capabilities"
import { catalogItemEnabled, selectionIdForModelCatalog } from "@/components/session/catalog-selection"

export function TaskGroupAgentSelect({ token, connectorId, runtimes, label, initialRuntimeId, disabled, onChange }: {
  token: string; connectorId: string; runtimes: DeviceRuntimeView[]; label: string; initialRuntimeId?: string; disabled: boolean
  onChange: (target: CandidateTarget | null) => void
}) {
  const t = useTranslations("taskGroups")
  const [runtimeId, setRuntimeId] = React.useState(initialRuntimeId ?? runtimes[0]?.runtimeId ?? "")
  const runtime = runtimes.find(row => row.runtimeId === runtimeId)
  const [catalogs, setCatalogs] = React.useState<{ runtimeId: string; model: ProtocolModelCatalog | null; permission: ProtocolPermissionCatalog | null } | null>(null)
  const [modelId, setModelId] = React.useState("")
  const [permissionId, setPermissionId] = React.useState("")
  const [error, setError] = React.useState("")
  const [retry, setRetry] = React.useState(0)
  const notify = React.useRef(onChange)
  notify.current = onChange

  React.useEffect(() => {
    let cancelled = false
    setCatalogs(null); setError(""); notify.current(null)
    if (!runtimeId) return
    void dashboardApi.getConnectorRuntimeCapabilities(token, connectorId, runtimeId).then(async ({ capabilitySet }) => {
      const scope = { runtimeId, runtimeType: runtime?.runtimeType }
      for (const id of [CAPABILITY.modelCatalog, CAPABILITY.permissionCatalog]) {
        const capability = findCapability(capabilitySet, id, scope)
        if (capability?.supported && !capabilityIsUsable(capabilitySet, id, scope)) throw new Error(capability.unavailableReason || "Agent settings unavailable")
      }
      const [model, permission] = await Promise.all([
        capabilityIsUsable(capabilitySet, CAPABILITY.modelCatalog, scope) ? dashboardApi.getConnectorRuntimeModelCatalog(token, connectorId, runtimeId).then(row => row.catalog) : null,
        capabilityIsUsable(capabilitySet, CAPABILITY.permissionCatalog, scope) ? dashboardApi.getConnectorRuntimePermissionCatalog(token, connectorId, runtimeId).then(row => row.catalog) : null,
      ])
      if (cancelled) return
      setModelId(model?.models.find(row => row.default && catalogItemEnabled(row))?.id ?? model?.models.find(catalogItemEnabled)?.id ?? "")
      setPermissionId(permission?.permissions.find(row => row.default && catalogItemEnabled(row))?.id ?? permission?.permissions.find(catalogItemEnabled)?.id ?? "")
      setCatalogs({ runtimeId, model, permission })
    }).catch(e => { if (!cancelled) setError(String(e.message ?? e)) })
    return () => { cancelled = true }
  }, [token, connectorId, runtimeId, runtime?.runtimeType, retry])

  React.useEffect(() => {
    const model = selectionIdForModelCatalog(catalogs?.model ?? null, modelId, "")
    const permission = catalogs?.permission?.permissions.find(row => row.id === permissionId && catalogItemEnabled(row))?.selectionId
    notify.current(runtime && catalogs?.runtimeId === runtimeId && (!catalogs.model || model) && (!catalogs.permission || permission)
      ? { runtime: runtime.runtimeType, runtimeId, selections: { ...(model ? { model } : {}), ...(permission ? { permission } : {}) } } : null)
  }, [runtime, runtimeId, catalogs, modelId, permissionId])

  return <div className="space-y-2">
    <Label className="grid gap-2">{label}<NativeSelect aria-label={label} value={runtimeId} disabled={disabled} onChange={e => { if (e.target.value !== runtimeId) { notify.current(null); setRuntimeId(e.target.value) } }}>
      {!runtimeId && <NativeSelectOption value="">{t("chooseAgents")}</NativeSelectOption>}
      {runtimes.map(row => <NativeSelectOption key={row.runtimeId} value={row.runtimeId}>{row.name || row.displayName} · {row.runtimeType}</NativeSelectOption>)}
    </NativeSelect></Label>
    {catalogs?.model && <Label className="grid gap-2">{t("model")}<NativeSelect aria-label={`${label} ${t("model")}`} value={modelId} disabled={disabled} onChange={e => setModelId(e.target.value)}>
      {catalogs.model.models.map(row => <NativeSelectOption key={row.id} value={row.id} disabled={!catalogItemEnabled(row)}>{row.group?.displayName ? `${row.group.displayName} · ` : ""}{row.displayName}</NativeSelectOption>)}
    </NativeSelect></Label>}
    {catalogs?.permission && <Label className="grid gap-2">{t("permission")}<NativeSelect aria-label={`${label} ${t("permission")}`} value={permissionId} disabled={disabled} onChange={e => setPermissionId(e.target.value)}>
      {catalogs.permission.permissions.map(row => <NativeSelectOption key={row.id} value={row.id} disabled={!catalogItemEnabled(row)}>{row.displayName}</NativeSelectOption>)}
    </NativeSelect></Label>}
    {!catalogs && !error && <p role="status" className="text-xs text-muted-foreground">{t("loadingAgent")}</p>}
    {error && <p role="alert" className="text-xs text-destructive">{error} <Button variant="ghost" size="sm" onClick={() => setRetry(n => n + 1)}>{t("retry")}</Button></p>}
  </div>
}
