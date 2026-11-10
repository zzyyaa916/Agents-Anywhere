"use client"

import { useTranslations } from "next-intl"
import { Settings2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Drawer, DrawerTrigger, DrawerContent, DrawerHeader, DrawerTitle, DrawerDescription } from "@/components/ui/drawer"
import { AgentConfigurationFields, useAgentConfiguration } from "@/components/task-group-agent-select"
import type { DeviceRuntimeView } from "@/features/dashboard/types"
import type { CandidateTarget } from "@/features/task-groups/api"

export function MultiAgentSettings({ token, connectorId, runtimes, disabled, onChange }: {
  token: string; connectorId: string; runtimes: DeviceRuntimeView[]; disabled: boolean
  onChange: (id: string, target: CandidateTarget | null) => void
}) {
  const t = useTranslations("taskGroups")
  // The selection is capped at three; keep hooks mounted when the drawer closes.
  const first = useAgentConfiguration(token, connectorId, runtimes[0], value => { if (runtimes[0]) onChange(runtimes[0].runtimeId, value) })
  const second = useAgentConfiguration(token, connectorId, runtimes[1], value => { if (runtimes[1]) onChange(runtimes[1].runtimeId, value) })
  const third = useAgentConfiguration(token, connectorId, runtimes[2], value => { if (runtimes[2]) onChange(runtimes[2].runtimeId, value) })
  return <Drawer direction="bottom">
    <DrawerTrigger asChild><Button variant="ghost" size="sm" disabled={disabled} className="h-8 gap-1.5 rounded-xl px-2.5 text-muted-foreground"><Settings2 className="size-3.5" /><span className="text-foreground">{t("settings")}</span></Button></DrawerTrigger>
    <DrawerContent><DrawerHeader><DrawerTitle>{t("settings")}</DrawerTitle><DrawerDescription>{t("settingsDescription")}</DrawerDescription></DrawerHeader>
      <div className="max-h-[58vh] space-y-5 overflow-y-auto px-4 pb-4">{runtimes.map((runtime, index) => <section key={runtime.runtimeId} className="space-y-3">
        <h3 className="text-sm font-medium">{runtime.name || runtime.displayName}</h3>
        <AgentConfigurationFields config={[first, second, third][index]!} label={runtime.name || runtime.displayName} disabled={disabled} />
      </section>)}</div>
    </DrawerContent>
  </Drawer>
}
