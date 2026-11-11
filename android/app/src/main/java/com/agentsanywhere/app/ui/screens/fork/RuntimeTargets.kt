package com.agentsanywhere.app.ui.screens.fork

import androidx.compose.runtime.*
import com.agentsanywhere.app.feature.devices.DeviceRuntimeList
import com.agentsanywhere.app.feature.devices.DeviceRuntimeStatus
import com.agentsanywhere.app.feature.sessions.*
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

@Composable
internal fun rememberRuntimeTargets(
    connectorId: String?,
    onList: suspend (String) -> Result<DeviceRuntimeList>,
    onCapabilities: suspend (String, String) -> Result<NewSessionRuntimeCapabilities>,
    onModels: suspend (String, String) -> Result<NewSessionModelCatalog>,
    onPermissions: suspend (String, String) -> Result<NewSessionPermissionCatalog>,
    refreshKey: Any? = null,
): androidx.compose.runtime.snapshots.SnapshotStateMap<String, NewSessionRuntimeSelectionState> {
    val configs = remember(connectorId) { mutableStateMapOf<String, NewSessionRuntimeSelectionState>() }
    LaunchedEffect(connectorId, refreshKey) {
        val previous = configs.toMap()
        configs.clear()
        val device = connectorId ?: return@LaunchedEffect
        onList(device).onSuccess { inventory -> coroutineScope {
            inventory.runtimes.filter { it.present && it.active && it.configured && it.status == DeviceRuntimeStatus.Running }.forEach { runtime -> launch {
                var config = NewSessionRuntimeSelectionState().beginRuntimeInventory(device)
                    .replaceRuntimeInventory(inventory, runtime.id).beginRuntimeDetails()
                val key = requireNotNull(config.requestKey)
                onCapabilities(device, runtime.id).onSuccess { config = config.applyCapabilities(key, it) }
                    .onFailure { config = config.failCapabilities(key, it.message ?: "能力加载失败") }
                if (config.canUseModelCatalog) onModels(device, runtime.id).onSuccess { config = config.applyModelCatalog(key, it) }
                    .onFailure { config = config.failModelCatalog(key, it.message ?: "模型加载失败") }
                if (config.canUsePermissionCatalog) onPermissions(device, runtime.id).onSuccess { config = config.applyPermissionCatalog(key, it) }
                    .onFailure { config = config.failPermissionCatalog(key, it.message ?: "权限加载失败") }
                previous[runtime.id]?.let { old ->
                    old.selectedModelId?.let { config = config.selectModel(it) }
                    old.selectedReasoningId?.let { config = config.selectReasoning(it) }
                    old.selectedPermissionId?.let { config = config.selectPermission(it) }
                }
                configs[runtime.id] = config
            } }
        } }
    }
    return configs
}
