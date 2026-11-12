package com.agentsanywhere.app.ui.screens.fork

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import com.agentsanywhere.app.R
import com.agentsanywhere.app.api.ApiException
import com.agentsanywhere.app.feature.fork.*
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

internal fun localUsageTime(value: String?): String = value?.let {
    runCatching { DateTimeFormatter.ofPattern("MM/dd HH:mm").withZone(ZoneId.systemDefault()).format(Instant.parse(it)) }.getOrNull()
} ?: "—"

@Composable
fun ForkUsageButton(controller: ForkController, modifier: Modifier = Modifier) {
    var open by remember(controller.scopeKey) { mutableStateOf(false) }
    var usage by remember(controller.scopeKey) { mutableStateOf<UsageCache?>(null) }
    var busy by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    fun load(refresh: Boolean) {
        if (busy) return
        busy = true
        scope.launch {
            controller.usage(refresh).onSuccess { usage = it; failed = false }.onFailure { failed = true }
            busy = false
        }
    }
    val usageDescription = stringResource(R.string.fork_usage)
    val remaining = usage?.accounts?.flatMap { account -> if (account.stale) emptyList() else account.windows.filterNot { it.expired() } }?.minOfOrNull { it.remaining }
    FilledTonalIconButton(onClick = { open = true; load(false) }, modifier = modifier.size(46.dp).semantics { contentDescription = usageDescription }) {
        Box {
            CircularProgressIndicator(progress = { ((remaining ?: 0.0) / 100).toFloat() }, modifier = Modifier.size(28.dp), strokeWidth = 3.dp)
            Text("◉", modifier = Modifier.padding(6.dp), style = MaterialTheme.typography.labelSmall)
        }
    }
    if (open) AlertDialog(onDismissRequest = { open = false }, title = { Text(stringResource(R.string.fork_usage)) }, text = {
        Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            usage?.accounts?.forEach { account ->
                Text("${if (account.runtime == "codex") "Codex" else "Claude Code"} · ${account.label}")
                account.windows.forEach { w ->
                    Text(stringResource(when (w.kind) { "five_hour" -> R.string.fork_five_hour; "weekly", "seven_day", "weekly_scoped" -> R.string.fork_weekly; else -> R.string.fork_other_window }) + (w.model?.let { " · $it" } ?: ""))
                    Text(if (w.expired()) stringResource(R.string.fork_expired) else stringResource(R.string.fork_remaining, w.remaining.roundToInt(), localUsageTime(w.resetsAt)))
                }
                if (account.windows.isEmpty()) Text(stringResource(R.string.fork_wait_native))
                Text(stringResource(if (account.stale) R.string.fork_stale else R.string.fork_updated, localUsageTime(account.fetchedAt)), style = MaterialTheme.typography.bodySmall)
            }
            (usage?.unavailable ?: listOf("codex", "claude_code")).forEach { runtime ->
                Text("${if (runtime == "codex") "Codex" else "Claude Code"} · " + stringResource(if (runtime == "claude_code") R.string.fork_wait_native else R.string.fork_unavailable))
            }
            if (failed) Text(stringResource(R.string.fork_failed), color = MaterialTheme.colorScheme.error)
            if (busy) Text(stringResource(R.string.fork_loading))
            Text(stringResource(R.string.fork_no_probe), style = MaterialTheme.typography.bodySmall)
        }
    }, confirmButton = { TextButton(onClick = { load(true) }, enabled = !busy) { Text(stringResource(R.string.fork_refresh)) } }, dismissButton = { TextButton(onClick = { open = false }) { Text(stringResource(R.string.fork_close)) } })
}

@Composable
fun ForkDeleteDialog(controller: ForkController, id: String, title: String, project: Boolean, onDismiss: () -> Unit, onDeleted: () -> Unit) {
    var count by remember(id) { mutableStateOf<Int?>(null) }
    var abandonConfirmed by remember(id) { mutableStateOf(false) }
    var confirmation by remember(id) { mutableStateOf("") }
    var busy by remember(id) { mutableStateOf(false) }
    var error by remember(id) { mutableStateOf<Throwable?>(null) }
    val scope = rememberCoroutineScope()
    suspend fun preview() { controller.deletionCount(id).onSuccess { count = it }.onFailure { error = it } }
    LaunchedEffect(id) { if (project) preview() }
    AlertDialog(onDismissRequest = { if (!busy) onDismiss() }, title = { Text(stringResource(if (project) R.string.fork_delete_project else R.string.fork_delete_session)) }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title)
            if (project) {
                if (count == null) Text(stringResource(R.string.fork_loading))
                else Text(stringResource(R.string.fork_delete_project_body, count!!))
                OutlinedTextField(value = confirmation, onValueChange = { confirmation = it }, enabled = !busy, label = { Text(stringResource(R.string.fork_confirm_name)) })
            } else Text(stringResource(R.string.fork_delete_session_body))
            error?.let { failure ->
                val api = failure as? ApiException
                Text(when {
                    api?.errorCode == "deletion_count_changed" -> stringResource(R.string.fork_count_changed)
                    api?.statusCode == 403 -> stringResource(R.string.fork_forbidden)
                    api?.statusCode == 409 -> stringResource(R.string.fork_busy, api.blockingSessionIds.joinToString(", "))
                    else -> stringResource(R.string.fork_failed)
                }, color = MaterialTheme.colorScheme.error)
                if (api?.errorCode in setOf("device_cleanup_incomplete", "deletion_cleanup_failed")) {
                    if (abandonConfirmed) Text(stringResource(R.string.fork_abandon_warning))
                    TextButton(enabled = !busy, onClick = {
                        if (!abandonConfirmed) abandonConfirmed = true
                        else {
                            busy = true
                            scope.launch {
                                controller.abandonCleanup(id, project).onSuccess { onDeleted() }.onFailure { error = it }
                                busy = false
                            }
                        }
                    }) { Text(stringResource(if (abandonConfirmed) R.string.fork_abandon_confirm else R.string.fork_abandon)) }
                }
                if (project && count == null) TextButton(onClick = { scope.launch { error = null; preview() } }) { Text(stringResource(R.string.fork_retry)) }
            }
        }
    }, confirmButton = { TextButton(enabled = !busy && (!project || (count != null && confirmation == title)), onClick = {
        busy = true
        scope.launch {
            val result = if (project) controller.deleteProject(id, count!!) else controller.deleteSession(id)
            result.onSuccess { onDeleted() }.onFailure { failure ->
                error = failure
                if (project && (failure as? ApiException)?.statusCode == 409) { confirmation = ""; preview() }
            }
            busy = false
        }
    }) { Text(stringResource(R.string.fork_delete), color = Color(0xFFC62828)) } }, dismissButton = { TextButton(onClick = onDismiss, enabled = !busy) { Text(stringResource(R.string.fork_cancel)) } })
}
