package com.agentsanywhere.app.ui.screens.fork

import com.agentsanywhere.app.R
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import com.agentsanywhere.app.feature.sessions.NewSessionRuntimeSelectionState
import com.agentsanywhere.app.feature.taskgroups.toggleRuntimeTarget
import java.util.UUID

@Composable
internal fun ForwardTargetsDialog(
    configs: MutableMap<String, NewSessionRuntimeSelectionState>, sourceRuntimeId: String,
    busy: Boolean, error: String?, onDismiss: () -> Unit,
    onForward: (String, String) -> Unit,
) {
    var selected by rememberSaveable { mutableStateOf(emptyList<String>()) }
    var instructions by rememberSaveable { mutableStateOf("请审核当前任务结果，指出问题及后续建议。") }
    var operation by rememberSaveable { mutableStateOf(UUID.randomUUID().toString()) }
    AlertDialog(onDismissRequest = { if (!busy) onDismiss() }, title = { Text(stringResource(R.string.fork_forward_title)) }, text = {
        Column(Modifier.verticalScroll(rememberScrollState())) {
            if (configs.isEmpty()) Text("正在加载可用 AI；加载失败时请关闭后重试。")
            configs.filterKeys { it != sourceRuntimeId }.forEach { (id, config) ->
                Row {
                    Checkbox(checked = id in selected, enabled = !busy && (id in selected || selected.size < 3), onCheckedChange = {
                        selected = toggleRuntimeTarget(selected, id); operation = UUID.randomUUID().toString()
                    })
                    Text(config.selectedRuntime?.labels?.primary ?: id)
                }
                if (id in selected) RuntimeConfiguration(config, !busy) { configs[id] = it; operation = UUID.randomUUID().toString() }
            }
            OutlinedTextField(instructions, { instructions = it; operation = UUID.randomUUID().toString() }, enabled = !busy, label = { Text(stringResource(R.string.fork_forward_instructions)) })
            Text("原任务、近期对话与附件会在同一项目中交给新会话。失败后保持输入重试。")
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }, confirmButton = { TextButton(enabled = !busy && instructions.isNotBlank() && selected.isNotEmpty() && selected.all { configs[it]?.readyForCreate == true }, onClick = {
        onForward("转发给 ${selected.joinToString("、")}：$instructions", operation)
    }) { Text(if (busy) "正在转发…" else "转发") } }, dismissButton = { TextButton(enabled = !busy, onClick = onDismiss) { Text("取消") } })
}
