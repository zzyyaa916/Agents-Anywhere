package com.agentsanywhere.app.ui.screens.fork

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.agentsanywhere.app.api.TaskGroup
import com.agentsanywhere.app.api.TaskGroupCandidate
import com.agentsanywhere.app.feature.devices.DeviceRuntimeList
import com.agentsanywhere.app.feature.devices.DeviceRuntimeStatus
import com.agentsanywhere.app.feature.sessiondetail.TimelineAttachment
import com.agentsanywhere.app.feature.sessions.*
import com.agentsanywhere.app.feature.taskgroups.*
import com.agentsanywhere.app.model.AgentProject
import com.agentsanywhere.app.ui.designsystem.runtimePermissionLocalizer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import kotlinx.coroutines.coroutineScope
import java.util.UUID

@Composable
fun CollaborationWorkbench(
    project: AgentProject,
    controller: TaskGroupsController,
    onListRuntimes: suspend (String) -> Result<DeviceRuntimeList>,
    onLoadCapabilities: suspend (String, String) -> Result<NewSessionRuntimeCapabilities>,
    onLoadModels: suspend (String, String) -> Result<NewSessionModelCatalog>,
    onLoadPermissions: suspend (String, String) -> Result<NewSessionPermissionCatalog>,
    onClose: () -> Unit,
    pane: @Composable (String, (((String) -> Boolean)?) -> Unit, suspend (String, List<TimelineAttachment>, String) -> Result<Boolean>) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var configs by remember(project.id) { mutableStateOf<Map<String, NewSessionRuntimeSelectionState>>(emptyMap()) }
    var selected by rememberSaveable(project.id) { mutableStateOf(emptyList<String>()) }
    var text by rememberSaveable(project.id) { mutableStateOf("") }
    var operation by rememberSaveable(project.id) { mutableStateOf(UUID.randomUUID().toString()) }
    var files by rememberSaveable(project.id) { mutableStateOf(emptyList<String>()) }
    var modelChoices by rememberSaveable(project.id) { mutableStateOf(hashMapOf<String, String>()) }
    var reasoningChoices by rememberSaveable(project.id) { mutableStateOf(hashMapOf<String, String>()) }
    var permissionChoices by rememberSaveable(project.id) { mutableStateOf(hashMapOf<String, String>()) }
    var groups by remember(project.id) { mutableStateOf(emptyList<TaskGroup>()) }
    var rootId by rememberSaveable(project.id) { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var retry by remember { mutableIntStateOf(0) }
    var unified by rememberSaveable(project.id) { mutableStateOf("") }
    val queues = remember { mutableStateMapOf<String, (String) -> Boolean>() }
    var excluded by rememberSaveable(project.id) { mutableStateOf(emptyList<String>()) }
    var forwardSource by remember { mutableStateOf<Pair<TaskGroup, TaskGroupCandidate>?>(null) }
    var forwardTarget by remember { mutableStateOf<String?>(null) }
    var forwardText by remember { mutableStateOf("请审核代码") }
    var forwardOperation by remember { mutableStateOf(UUID.randomUUID().toString()) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        try { files = retainTaskGroupAttachments(context.applicationContext, uris); operation = UUID.randomUUID().toString() } catch (failure: Exception) { error = failure.message }
    }
    fun configure(id: String, value: NewSessionRuntimeSelectionState) {
        configs = configs + (id to value)
        modelChoices = HashMap(modelChoices).apply { value.selectedModelId?.let { put(id, it) } }
        reasoningChoices = HashMap(reasoningChoices).apply { value.selectedReasoningId?.let { put(id, it) } }
        permissionChoices = HashMap(permissionChoices).apply { value.selectedPermissionId?.let { put(id, it) } }
    }
    fun update(group: TaskGroup) { groups = groups.filterNot { it.id == group.id } + group }
    suspend fun refresh() { controller.restore(project.id, rootId).onSuccess { groups = it }.onFailure { error = it.message } }
    suspend fun forward(group: TaskGroup, slot: Int, message: String, attachments: List<TimelineAttachment>, id: String): Result<Boolean> {
        return try {
            val command = parseForwardCommand(message, configs.values.mapNotNull { it.selectedRuntime }) ?: return Result.success(false)
            val target = requireNotNull(configs[command.runtimeId]) { "目标 AI 配置尚未加载" }
            val next = controller.handoff(id.replace('_', '-'), group.id, slot, target, command.instructions, attachments.map { it.fileId }).getOrThrow()
            update(next)
            // start is a one-time claim; an unknown result must be inspected, never replayed as a new operation.
            controller.start(next.id, 0).onSuccess(::update).onFailure { error = "转发已创建，请刷新查看投递结果：${it.message}" }
            Result.success(true)
        } catch (cancel: CancellationException) { throw cancel }
        catch (failure: Exception) { Result.failure(failure) }
    }
    LaunchedEffect(project.id, retry) {
        refresh()
        onListRuntimes(project.connectorId).onSuccess { inventory ->
            val runtimes = inventory.runtimes.filter { it.present && it.active && it.configured && it.status == DeviceRuntimeStatus.Running }
            coroutineScope {
                runtimes.forEach { runtime -> launch {
                    var config = NewSessionRuntimeSelectionState().beginRuntimeInventory(project.connectorId)
                        .replaceRuntimeInventory(inventory, runtime.id).beginRuntimeDetails()
                    val key = requireNotNull(config.requestKey)
                    onLoadCapabilities(project.connectorId, runtime.id).onSuccess { config = config.applyCapabilities(key, it) }
                        .onFailure { config = config.failCapabilities(key, it.message ?: "能力加载失败") }
                    if (config.canUseModelCatalog) onLoadModels(project.connectorId, runtime.id)
                        .onSuccess { config = config.applyModelCatalog(key, it) }.onFailure { config = config.failModelCatalog(key, it.message ?: "模型加载失败") }
                    if (config.canUsePermissionCatalog) onLoadPermissions(project.connectorId, runtime.id)
                        .onSuccess { config = config.applyPermissionCatalog(key, it) }.onFailure { config = config.failPermissionCatalog(key, it.message ?: "权限加载失败") }
                    modelChoices[runtime.id]?.let { config = config.selectModel(it) }
                    reasoningChoices[runtime.id]?.let { config = config.selectReasoning(it) }
                    permissionChoices[runtime.id]?.let { config = config.selectPermission(it) }
                    configs = configs + (runtime.id to config)
                } }
            }
        }.onFailure { error = it.message }
    }
    LaunchedEffect(rootId) { if (rootId != null) refresh() }
    val visibleIds = remember(groups, rootId) { taskGroupChain(groups, rootId) }
    val panes = groups.filter { it.id in visibleIds }.flatMap { group -> group.candidates.map { group to it } }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Surface(Modifier.fillMaxSize().systemBarsPadding().imePadding()) {
            Column(Modifier.fillMaxSize()) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = onClose) { Text("返回") }
                    Text("原生多 AI 工作台", modifier = Modifier.padding(top = 12.dp))
                    TextButton(enabled = !busy, onClick = { scope.launch { refresh() } }) { Text("刷新") }
                }
                error?.let { message -> Row { Text(message, color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f).padding(8.dp)); TextButton(onClick = { error = null }) { Text("关闭") } } }
                if (rootId == null) Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("${project.name} · ${project.workspacePath}")
                    Text("选择 1–3 个 AI，分别在独立代码工作区执行。")
                    if (configs.isEmpty()) TextButton(onClick = { retry++ }) { Text("加载可用 AI / 重试") }
                    configs.forEach { (id, config) ->
                        Row {
                            Checkbox(checked = id in selected, enabled = !busy && (id in selected || selected.size < 3), onCheckedChange = { checked ->
                                selected = if (checked) selected + id else selected - id; operation = UUID.randomUUID().toString()
                            })
                            Column(Modifier.weight(1f)) {
                                Text(config.selectedRuntime?.displayName ?: id)
                                if (id in selected) RuntimeConfiguration(config, enabled = !busy) { configure(id, it); operation = UUID.randomUUID().toString() }
                            }
                        }
                    }
                    OutlinedTextField(value = text, onValueChange = { text = it; operation = UUID.randomUUID().toString() }, enabled = !busy, label = { Text("初始任务（所有选中 AI 同时收到）") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
                    TextButton(enabled = !busy, onClick = { picker.launch(arrayOf("*/*")) }) { Text("选择附件（${files.size}/10）") }
                    if (files.isNotEmpty()) TextButton(enabled = !busy, onClick = { files = emptyList(); operation = UUID.randomUUID().toString() }) { Text("移除附件") }
                    Button(enabled = !busy && text.isNotBlank() && selected.isNotEmpty() && selected.all { configs[it]?.readyForCreate == true }, onClick = {
                        busy = true; error = null
                        val submittedText = text; val submittedOperation = operation; val submittedFiles = files; val submittedConfigs = selected.mapNotNull(configs::get)
                        scope.launch {
                            try {
                                val parts = readTaskGroupAttachments(context.applicationContext, submittedFiles.map(android.net.Uri::parse))
                                val group = controller.create(submittedOperation, project.id, submittedText, submittedConfigs, parts).getOrThrow()
                                update(group); rootId = group.id
                                text = ""; files = emptyList(); operation = UUID.randomUUID().toString()
                                coroutineScope { group.candidates.forEach { candidate -> launch {
                                    controller.start(group.id, candidate.slot).onSuccess(::update).onFailure { error = "任务组已创建，请刷新查看结果：${it.message}" }
                                } } }
                                refresh()
                            } catch (cancel: CancellationException) { throw cancel }
                            catch (failure: Exception) { error = "${failure.message}。请先查看历史任务组；重试将复用本次任务标识。"; refresh() }
                            finally { busy = false }
                        }
                    }) { Text(if (busy) "正在创建…" else "发送给所选 AI") }
                    Text("历史任务组（点击恢复）")
                    groups.take(30).forEach { group -> TextButton(onClick = { rootId = group.id }) { Text(group.content.take(60)) } }
                } else {
                    Row { TextButton(onClick = { rootId = null }) { Text("新任务 / 历史") }; Text("横向滑动查看各 AI", modifier = Modifier.padding(top = 12.dp)) }
                    BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                        val paneWidth = if (maxWidth > 800.dp) maxWidth / 2 else maxWidth
                        Row(Modifier.fillMaxSize().horizontalScroll(rememberScrollState())) {
                            panes.forEach { (group, candidate) -> key(group.id, candidate.slot) {
                                val session = candidate.sessionId
                                Column(Modifier.width(paneWidth).fillMaxHeight()) {
                                    Row {
                                        Checkbox(checked = session != null && session !in excluded, enabled = session != null, onCheckedChange = { checked -> session?.let { excluded = if (checked) excluded - it else excluded + it } })
                                        Text(configs[candidate.runtimeId]?.selectedRuntime?.displayName ?: candidate.runtimeId, modifier = Modifier.weight(1f).padding(top = 12.dp))
                                        TextButton(enabled = !busy, onClick = { forwardSource = group to candidate; forwardTarget = configs.keys.firstOrNull(); forwardOperation = UUID.randomUUID().toString() }) { Text("转发") }
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
                                        pane(session, { accept -> if (accept == null) queues.remove(session) else queues[session] = accept },
                                            { message, attachments, id -> forward(group, candidate.slot, message, attachments, id) })
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
    forwardSource?.let { (group, candidate) ->
        AlertDialog(onDismissRequest = { if (!busy) forwardSource = null }, title = { Text("转发给任意可用 AI") }, text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                configs.forEach { (id, config) -> Row {
                    RadioButton(selected = forwardTarget == id, enabled = !busy, onClick = { forwardTarget = id; forwardOperation = UUID.randomUUID().toString() })
                    Text(config.selectedRuntime?.displayName ?: id, Modifier.padding(top = 12.dp))
                } }
                configs[forwardTarget]?.let { config -> RuntimeConfiguration(config, !busy) { configure(requireNotNull(forwardTarget), it); forwardOperation = UUID.randomUUID().toString() } }
                OutlinedTextField(value = forwardText, enabled = !busy, onValueChange = { forwardText = it; forwardOperation = UUID.randomUUID().toString() }, label = { Text("审核或继续执行指令") })
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Text("来源须先完成任务。原始任务、代码快照、近期对话及附件由服务端一起交接。")
            }
        }, confirmButton = { TextButton(enabled = !busy && forwardText.isNotBlank() && configs[forwardTarget]?.readyForCreate == true, onClick = {
            busy = true
            scope.launch {
                try {
                    val result = forward(group, candidate.slot, "转发给 ${forwardTarget}：$forwardText", emptyList(), forwardOperation)
                    if (result.getOrNull() == true) forwardSource = null else error = result.exceptionOrNull()?.message
                } finally { busy = false }
            }
        }) { Text("转发") } }, dismissButton = { TextButton(enabled = !busy, onClick = { forwardSource = null }) { Text("取消") } })
    }
}

@Composable
private fun RuntimeConfiguration(config: NewSessionRuntimeSelectionState, enabled: Boolean, onChange: (NewSessionRuntimeSelectionState) -> Unit) {
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
