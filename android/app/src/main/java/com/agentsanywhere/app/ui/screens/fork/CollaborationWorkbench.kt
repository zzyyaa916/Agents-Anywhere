package com.agentsanywhere.app.ui.screens.fork

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.agentsanywhere.app.api.TaskGroup
import com.agentsanywhere.app.feature.sessions.*
import com.agentsanywhere.app.feature.taskgroups.*
import com.agentsanywhere.app.model.AgentProject
import com.agentsanywhere.app.model.runtimeTypeLabel
import com.agentsanywhere.app.ui.designsystem.runtimePermissionLocalizer
import kotlinx.coroutines.launch

@Composable
fun CollaborationWorkbench(
    project: AgentProject,
    initialGroupId: String? = null,
    controller: TaskGroupsController,
    onClose: () -> Unit,
    pane: @Composable (String, (((String) -> Boolean)?) -> Unit) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var groups by remember(project.id) { mutableStateOf(emptyList<TaskGroup>()) }
    var rootId by rememberSaveable(project.id, initialGroupId) { mutableStateOf(initialGroupId) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var retry by remember { mutableIntStateOf(0) }
    var unified by rememberSaveable(project.id) { mutableStateOf("") }
    val queues = remember { mutableStateMapOf<String, (String) -> Boolean>() }
    var excluded by rememberSaveable(project.id) { mutableStateOf(emptyList<String>()) }
    fun update(group: TaskGroup) { groups = groups.filterNot { it.id == group.id } + group }
    suspend fun refresh() { controller.restore(project.id, rootId).onSuccess { groups = it }.onFailure { error = it.message } }
    LaunchedEffect(project.id, rootId, retry) { refresh() }
    val visibleIds = remember(groups, rootId) { taskGroupChain(groups, rootId) }
    val panes = visibleIds.mapNotNull { id -> groups.firstOrNull { it.id == id } }.flatMap { group -> group.candidates.map { group to it } }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Surface(Modifier.fillMaxSize().systemBarsPadding().imePadding()) {
            Column(Modifier.fillMaxSize()) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = onClose) { Text("返回") }
                    Text("多 AI 会话", modifier = Modifier.padding(top = 12.dp))
                    TextButton(enabled = !busy, onClick = { scope.launch { refresh() } }) { Text("刷新") }
                }
                error?.let { message -> Row { Text(message, color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f).padding(8.dp)); TextButton(onClick = { error = null }) { Text("关闭") } } }
                if (rootId == null) Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("历史任务组（点击恢复）")
                    groups.take(30).forEach { group -> TextButton(onClick = { rootId = group.id }) { Text(group.content.take(60)) } }
                } else {
                    Row { TextButton(onClick = { rootId = null }) { Text("历史任务") }; Text("横向滑动查看各 AI", modifier = Modifier.padding(top = 12.dp)) }
                    BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                        val paneWidth = if (maxWidth > 800.dp) maxWidth / 2 else maxWidth
                        Row(Modifier.fillMaxSize().horizontalScroll(rememberScrollState())) {
                            panes.forEach { (group, candidate) -> key(group.id, candidate.slot) {
                                val session = candidate.sessionId
                                Column(Modifier.width(paneWidth).fillMaxHeight()) {
                                    Row {
                                        Checkbox(checked = session != null && session !in excluded, enabled = session != null, onCheckedChange = { checked -> session?.let { excluded = if (checked) excluded - it else excluded + it } })
                                        Text(candidate.runtimeType.runtimeTypeLabel(), modifier = Modifier.weight(1f).padding(top = 12.dp))
                                    }
                                    if (session == null) {
                                        Text(candidate.error ?: "等待启动：${candidate.phase}")
                                        if (group.phase != "ready") Text("工作区准备尚未完成；请返回原任务重试，保留操作标识。")
                                        if (group.phase == "ready" && candidate.phase == "pending") TextButton(enabled = !busy, onClick = {
                                            busy = true; scope.launch { try { controller.start(group.id, candidate.slot).onSuccess(::update).onFailure { error = it.message } } finally { busy = false } }
                                        }) { Text("启动此 AI") }
                                    } else {
                                        if (candidate.phase in listOf("unknown", "dispatching")) Text("投递结果待确认，请先查看原会话，勿重复创建。", color = MaterialTheme.colorScheme.error)
                                        Box(Modifier.weight(1f)) {
                                        pane(session, { accept -> if (accept == null) queues.remove(session) else queues[session] = accept })
                                        }
                                    }
                                }
                            } }
                        }
                    }
                    Row(Modifier.padding(8.dp)) {
                        OutlinedTextField(value = unified, onValueChange = { unified = it }, label = { Text("统一输入：空闲即发，忙碌排队") }, modifier = Modifier.weight(1f).testTag("task-unified-input"), maxLines = 4)
                        Button(enabled = unified.isNotBlank() && panes.any { it.second.sessionId?.let { id -> id !in excluded && id in queues } == true }, onClick = {
                            val targets = panes.mapNotNull { it.second.sessionId }.distinct().filter { it !in excluded }
                            val failed = targets.filter { queues[it]?.invoke(unified.trim()) != true }
                            if (failed.isEmpty()) { unified = ""; error = null } else {
                                // Successful queues keep their copy; select only failed targets for a safe retry.
                                excluded = (excluded + (targets - failed)).distinct()
                                error = "${failed.size} 个会话尚未就绪，已仅保留失败目标，避免重复发送。"
                            }
                        }) { Text("发送") }
                    }
                }
            }
        }
    }
}

@Composable
internal fun RuntimeConfiguration(config: NewSessionRuntimeSelectionState, enabled: Boolean, onChange: (NewSessionRuntimeSelectionState) -> Unit) {
    val localizer = runtimePermissionLocalizer()
    val failure = config.capabilities.errorMessage ?: config.modelCatalog.errorMessage ?: config.permissionCatalog.errorMessage
    failure?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    if (!config.capabilities.fresh) Text("正在加载 AI 能力…")
    NativeChoice("模型", config.selectedModel?.displayName, config.modelCatalog.data?.models.orEmpty().filter { it.enabled }.map { it.id to it.displayName }, enabled) { onChange(config.selectModel(it)) }
    NativeChoice("推理强度", config.selectedReasoning?.displayName?.let(::reasoningLabel), config.selectedModel?.reasoningItems.orEmpty().filter { it.enabled }.map { it.id to reasoningLabel(it.displayName) }, enabled) { onChange(config.selectReasoning(it)) }
    val permissions = config.permissionCatalog.data?.permissions.orEmpty().filter { it.enabled }.map { permission ->
        permission.id to localizer.localize(config.selectedRuntime?.type, permission.id, permission.displayName, permission.description, permission.metadata).label
    }
    NativeChoice("权限", permissions.firstOrNull { it.first == config.selectedPermissionId }?.second, permissions, enabled) { onChange(config.selectPermission(it)) }
}
private fun reasoningLabel(value: String): String = when (value.lowercase()) { "none" -> "无"; "minimal" -> "最低"; "low" -> "低"; "medium" -> "中"; "high" -> "高"; "xhigh", "extra high" -> "最高"; else -> value }

@Composable
private fun NativeChoice(label: String, selected: String?, options: List<Pair<String, String>>, enabled: Boolean, onSelect: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    if (options.isNotEmpty()) Box {
        TextButton(enabled = enabled, onClick = { expanded = true }) { Text("$label：${selected ?: "请选择"}") }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { (id, name) -> DropdownMenuItem(text = { Text(name) }, onClick = { expanded = false; onSelect(id) }) }
        }
    }
}
