package com.agentsanywhere.app.ui.screens.fork

import com.agentsanywhere.app.R
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.agentsanywhere.app.api.TaskGroup
import com.agentsanywhere.app.feature.taskgroups.*
import com.agentsanywhere.app.model.AgentProject
import com.agentsanywhere.app.model.AgentSession

@Composable
internal fun JointConversations(
    scopeKey: String, projects: List<AgentProject>, sessions: List<AgentSession>,
    controller: TaskGroupsController, onLoadSessions: (String) -> Unit,
    onRestoreGroup: (AgentProject, String) -> Unit, onClose: () -> Unit,
    pane: @Composable (String, (((String) -> Boolean)?) -> Unit) -> Unit,
) {
    val context = LocalContext.current
    val store = remember(scopeKey) { JointConversationStore(context, scopeKey) }
    var state by remember(store) { mutableStateOf(store.read()) }
    fun update(next: JointConversationState) { store.save(next); state = next }
    val queues = remember(scopeKey) { mutableStateMapOf<String, (String) -> Boolean>() }
    var groups by remember(state.projectId) { mutableStateOf(emptyList<TaskGroup>()) }
    var error by remember { mutableStateOf<String?>(null) }
    var displaying by remember { mutableStateOf(state.sessions.size == 2) }
    val project = projects.firstOrNull { it.id == state.projectId }
    val choices = sessions.filter { it.projectId == state.projectId && !it.archived }.distinctBy { it.id }
    val selected = state.sessions.mapNotNull { id -> choices.firstOrNull { it.id == id } }
    val validSelection = project != null && selected.size == 2 && selected.map { it.runtimeType }.distinct().size == 2
    LaunchedEffect(state.projectId) {
        if (project != null) {
            onLoadSessions(project.id)
            controller.list(project.id).onSuccess { groups = it }.onFailure { error = it.message }
        }
    }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Surface(Modifier.fillMaxSize().systemBarsPadding().imePadding()) {
            Column(Modifier.fillMaxSize()) {
                Row { TextButton(onClick = onClose) { Text("返回") }; TextButton(onClick = { displaying = !displaying }) { Text(if (displaying) "选择会话 / 恢复任务" else "联立显示") } }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                if (!displaying || !validSelection) Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(12.dp)) {
                    Text(stringResource(R.string.fork_joint_select))
                    projects.forEach { item -> Row {
                        RadioButton(selected = state.projectId == item.id, onClick = { if (state.projectId != item.id) update(JointConversationState(projectId = item.id)) })
                        Text(item.name)
                    } }
                    choices.forEach { item -> Row {
                        val checked = item.id in state.sessions
                        Checkbox(checked = checked, enabled = checked || (selected.size < 2 && selected.none { it.runtimeType == item.runtimeType }), onCheckedChange = {
                            update(state.copy(sessions = if (checked) selected.map { it.id } - item.id else selected.map { it.id } + item.id, excluded = emptySet(), hidden = emptySet()))
                        })
                        Text("${item.runtimeLabel} · ${item.title}")
                    } }
                    Button(enabled = validSelection, onClick = { displaying = true }) { Text(stringResource(R.string.fork_joint_show)) }
                    Text(stringResource(R.string.fork_multi_history))
                    groups.forEach { group -> TextButton(onClick = { project?.let { onRestoreGroup(it, group.id) } }) { Text(group.content.take(60)) } }
                } else {
                    Row { selected.forEach { session ->
                        TextButton(onClick = { update(state.copy(hidden = if (session.id in state.hidden) state.hidden - session.id else state.hidden + session.id)) }) { Text(if (session.id in state.hidden) "显示 ${session.runtimeLabel}" else "收起 ${session.runtimeLabel}") }
                    } }
                    BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                        val paneWidth = if (maxWidth > 800.dp) maxWidth / 2 else maxWidth
                        Row(Modifier.fillMaxSize().horizontalScroll(rememberScrollState())) {
                            selected.forEach { session -> key(session.id) {
                                Column(Modifier.width(if (session.id in state.hidden) 0.dp else paneWidth).fillMaxHeight()) {
                                    Row {
                                        Checkbox(checked = session.id !in state.excluded, onCheckedChange = { checked -> update(state.copy(excluded = if (checked) state.excluded - session.id else state.excluded + session.id)) })
                                        Text(session.runtimeLabel)
                                    }
                                    Box(Modifier.weight(1f)) { pane(session.id) { accept -> if (accept == null) queues.remove(session.id) else queues[session.id] = accept } }
                                }
                            } }
                        }
                    }
                    Row(Modifier.padding(8.dp)) {
                        OutlinedTextField(state.draft, { update(state.copy(draft = it)) }, label = { Text("联立发布：空闲即发，忙碌排队") }, modifier = Modifier.weight(1f), maxLines = 4)
                        Button(enabled = state.draft.isNotBlank() && selected.any { it.id !in state.excluded && it.id in queues }, onClick = {
                            val targets = selected.map { it.id }.filter { it !in state.excluded }
                            val accepted = targets.filter { queues[it]?.invoke(state.draft.trim()) == true }
                            if (accepted.size == targets.size) { update(state.copy(draft = "")); error = null }
                            else { update(state.copy(excluded = state.excluded + accepted)); error = "部分会话未就绪，仅重试未接收的目标" }
                        }) { Text(stringResource(R.string.fork_joint_publish)) }
                    }
                }
            }
        }
    }
}
