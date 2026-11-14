package com.agentsanywhere.app.ui.screens.fork

import com.agentsanywhere.app.R
import androidx.compose.ui.res.stringResource
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import com.agentsanywhere.app.feature.sessions.NewSessionRuntimeSelectionState
import com.agentsanywhere.app.feature.taskgroups.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.util.UUID

@Composable
internal fun TaskGroupComposer(projectId: String, configs: List<NewSessionRuntimeSelectionState>, controller: TaskGroupsController, onCreated: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var text by rememberSaveable(projectId) { mutableStateOf("") }
    var files by rememberSaveable(projectId) { mutableStateOf(emptyList<String>()) }
    var operation by rememberSaveable(projectId) { mutableStateOf(UUID.randomUUID().toString()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var accepted by rememberSaveable(projectId) { mutableStateOf<String?>(null) }
    // Edits produce a new operation; unchanged retries keep the original identity.
    LaunchedEffect(configs.map { it.selectedRuntimeId to it.selections }) { operation = UUID.randomUUID().toString() }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        try { files = retainTaskGroupAttachments(context.applicationContext, uris); operation = UUID.randomUUID().toString() }
        catch (failure: Exception) { error = failure.message }
    }
    Column {
        OutlinedTextField(text, { text = it; operation = UUID.randomUUID().toString() }, enabled = !busy && accepted == null, label = { Text(stringResource(R.string.fork_multi_send)) }, modifier = Modifier.fillMaxWidth().heightIn(max = 120.dp), minLines = 1, maxLines = 4)
        Row {
            TextButton(enabled = !busy && accepted == null && configs.all { it.canUseAttachments }, onClick = { picker.launch(arrayOf("*/*")) }) { Text("附件（${files.size}/10）") }
            if (files.isNotEmpty()) TextButton(enabled = !busy && accepted == null, onClick = { files = emptyList(); operation = UUID.randomUUID().toString() }) { Text("移除附件") }
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        val created = accepted
        if (created != null) TextButton(onClick = { onCreated(created) }) { Text("恢复已创建任务") }
        Button(enabled = !busy && created == null && text.isNotBlank() && configs.size in 2..3 && configs.all { it.readyForCreate }, onClick = {
            busy = true; error = null
            val submittedConfigs = configs; val submittedText = text; val submittedOperation = operation; val submittedFiles = files
            scope.launch {
                try {
                    val parts = readTaskGroupAttachments(context.applicationContext, submittedFiles.map(android.net.Uri::parse))
                    val group = controller.create(submittedOperation, projectId, submittedText, submittedConfigs, parts).getOrThrow()
                    accepted = group.id
                    // Start claims once; the workbench exposes pending/unknown states after failures.
                    for (candidate in group.candidates) if (candidate.phase == "pending" && group.phase == "ready") controller.start(group.id, candidate.slot)
                    onCreated(group.id)
                } catch (cancel: CancellationException) { throw cancel }
                catch (failure: Exception) { error = "${failure.message}。未改动输入时重试会复用任务标识。" }
                finally { busy = false }
            }
        }) { Text(if (busy) "正在发送…" else "发送") }
    }
}
