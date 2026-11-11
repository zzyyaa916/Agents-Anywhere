import { runtimeLabel } from "@/components/session/session-utils"
import { dashboardApi } from "@/features/dashboard/api"
import type { DeviceRuntimeView } from "@/features/dashboard/types"
import type { CandidateTarget } from "./api"
import { CAPABILITY, capabilityIsUsable, findCapability } from "@/components/session/capabilities"
import { catalogItemEnabled, selectionIdForModelCatalog } from "@/components/session/catalog-selection"

export function forwardRuntimeNames(runtime: DeviceRuntimeView) {
  return [runtime.runtimeId, runtime.runtimeType, runtime.name, runtime.displayName, runtime.typeDisplayName, runtimeLabel(runtime.runtimeType)].filter((name): name is string => Boolean(name))
}

export async function resolveForwardTargets(token: string, connectorId: string, runtimes: DeviceRuntimeView[], names: string[], configured: CandidateTarget[] = []) {
  if (names.length < 1 || names.length > 3) throw new Error("请选择 1～3 个目标 AI。")
  const selected = names.map(name => {
    const matches = runtimes.filter(runtime => runtime.status === "running" && forwardRuntimeNames(runtime).some(value => value.toLowerCase() === name.toLowerCase()))
    if (matches.length !== 1) throw new Error(`目标 AI「${name}」不存在或名称不唯一，请使用转发按钮选择。`)
    return matches[0]!
  })
  if (new Set(selected.map(runtime => runtime.runtimeId)).size !== selected.length) throw new Error("请为每个目标选择不同的 AI。")
  const targets: CandidateTarget[] = []
  for (const runtime of selected) {
    const existing = configured.find(row => row.runtimeId === runtime.runtimeId)
    if (existing) { targets.push(existing); continue }
    const { capabilitySet } = await dashboardApi.getConnectorRuntimeCapabilities(token, connectorId, runtime.runtimeId)
    const scope = { runtimeId: runtime.runtimeId, runtimeType: runtime.runtimeType }
    for (const id of [CAPABILITY.modelCatalog, CAPABILITY.permissionCatalog]) {
      if (findCapability(capabilitySet, id, scope)?.supported && !capabilityIsUsable(capabilitySet, id, scope)) throw new Error("目标 AI 设置暂不可用，请稍后重试。")
    }
    const selections: Record<string, string | null> = {}
    if (capabilityIsUsable(capabilitySet, CAPABILITY.modelCatalog, scope)) {
      const { catalog } = await dashboardApi.getConnectorRuntimeModelCatalog(token, connectorId, runtime.runtimeId)
      const model = catalog.models.find(row => row.default && catalogItemEnabled(row)) ?? catalog.models.find(catalogItemEnabled)
      const reasoning = model?.reasoningItems.find(row => row.default && catalogItemEnabled(row)) ?? model?.reasoningItems.find(catalogItemEnabled)
      const selection = selectionIdForModelCatalog(catalog, model?.id ?? "", reasoning?.id ?? "")
      if (!selection) throw new Error("目标 AI 没有可用模型，请使用转发按钮检查设置。")
      selections.model = selection
    }
    if (capabilityIsUsable(capabilitySet, CAPABILITY.permissionCatalog, scope)) {
      const { catalog } = await dashboardApi.getConnectorRuntimePermissionCatalog(token, connectorId, runtime.runtimeId)
      const permission = catalog.permissions.find(row => row.default && catalogItemEnabled(row)) ?? catalog.permissions.find(catalogItemEnabled)
      if (!permission) throw new Error("目标 AI 没有可用权限，请使用转发按钮检查设置。")
      selections.permission = permission.selectionId
    }
    targets.push({ runtime: runtime.runtimeType, runtimeId: runtime.runtimeId, selections })
  }
  return targets
}
