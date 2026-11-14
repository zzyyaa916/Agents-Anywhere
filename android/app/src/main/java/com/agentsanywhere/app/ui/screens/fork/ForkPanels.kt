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

internal fun claudeUpdate(windows: List<UsageWindow>): String {
    val latest = windows.maxByOrNull { window -> runCatching { Instant.parse(window.receivedAt).toEpochMilli() }.getOrDefault(Long.MIN_VALUE) }
    return "${if (latest?.receivedAt != null) localUsageTime(latest.receivedAt) + " 更新" else "更新时间未知"} · ${if (latest?.source == "probe") "探针" else "缓存"}"
}

@Composable
fun ForkUsageButton(controller: ForkController, modifier: Modifier = Modifier) {
    var open by remember(controller.scopeKey) { mutableStateOf(false) }
    var usage by remember(controller.scopeKey) { mutableStateOf<UsageCache?>(null) }
    var busy by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    var loadedAt by remember { mutableStateOf(android.os.SystemClock.elapsedRealtime()) }
    var elapsed by remember { mutableStateOf(0.0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(open) {
        while (open) {
            elapsed = (android.os.SystemClock.elapsedRealtime() - loadedAt).coerceAtLeast(0) / 1000.0
            kotlinx.coroutines.delay(1000)
        }
    }
    fun load(refresh: Boolean) {
        if (busy) return
        busy = true
        scope.launch {
            controller.usage(refresh).onSuccess {
                usage = it; failed = false; loadedAt = android.os.SystemClock.elapsedRealtime(); elapsed = 0.0
            }.onFailure { failed = true }
            busy = false
        }
    }
    val usageDescription = stringResource(R.string.fork_usage)
    val remaining = usage?.accounts?.flatMap { it.windows }?.minOfOrNull { it.remaining }
    FilledTonalIconButton(onClick = { open = true; load(false) }, modifier = modifier.size(46.dp).semantics { contentDescription = usageDescription }) {
        Box {
            CircularProgressIndicator(progress = { ((remaining ?: 0.0) / 100).toFloat() }, modifier = Modifier.size(28.dp), strokeWidth = 3.dp)
            Text("◉", modifier = Modifier.padding(6.dp), style = MaterialTheme.typography.labelSmall)
        }
    }
    val status = usage?.refresh?.status ?: "idle"
    val serverNow = usage?.serverTime?.let { runCatching { Instant.parse(it).toEpochMilli() / 1000.0 + elapsed }.getOrNull() } ?: 0.0
    val deadline = usage?.refresh?.nextAllowedAt?.let { runCatching { Instant.parse(it).toEpochMilli() / 1000.0 }.getOrNull() } ?: 0.0
    val cooling = status == "success" && deadline > serverNow
    val cooldownSeconds = kotlin.math.ceil((deadline - serverNow).coerceAtLeast(0.0)).toInt()
    val blocked = (status in setOf("retry", "offline", "circuit") || cooling) && deadline > serverNow
    val pending = busy || (status == "running" && (deadline == 0.0 || deadline > serverNow))
    val label = when {
        pending -> "请求中…"
        cooling -> "${cooldownSeconds} 秒后可刷新"
        status == "circuit" && blocked -> "今日探针已熔断，明日恢复"
        failed || status in setOf("retry", "offline") || (status == "running" && !pending) -> "稍后重试"
        status == "disabled" -> "未配置探针"
        else -> "刷新"
    }
    if (open) AlertDialog(onDismissRequest = { open = false }, title = { Text(stringResource(R.string.fork_usage)) }, text = {
        Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (cooling) Text("上次探针已成功，${cooldownSeconds} 秒后可再次刷新。")
            if (status == "offline") Text("探针节点离线")
            if (status in setOf("retry", "offline", "circuit") && deadline > 0) Text("可重试时间：${localUsageTime(usage?.refresh?.nextAllowedAt)}")
            if (failed) Text("刷新失败，原有数据保留", color = MaterialTheme.colorScheme.error)
            usage?.accounts?.forEach { account ->
                Text("${if (account.runtime == "codex") "Codex" else "Claude Code"} · ${account.label}")
                account.windows.forEach { window ->
                    Text(stringResource(when (window.kind) { "five_hour" -> R.string.fork_five_hour; "weekly", "seven_day", "weekly_scoped" -> R.string.fork_weekly; else -> R.string.fork_other_window }))
                    Text("剩余 ${window.remaining.roundToInt()}%")
                    Text("重置时间：${localUsageTime(window.resetsAt)}")
                }
                if (account.runtime == "claude_code" && account.windows.isNotEmpty()) Text(claudeUpdate(account.windows), style = MaterialTheme.typography.bodySmall)
                if (account.runtime == "codex") Text(stringResource(if (account.stale) R.string.fork_stale else R.string.fork_updated, localUsageTime(account.fetchedAt)), style = MaterialTheme.typography.bodySmall)
            }
            if (usage?.accounts.isNullOrEmpty()) Text("暂无数据")
        }
    }, confirmButton = { TextButton(onClick = { load(true) }, enabled = !pending && !blocked && status != "disabled") { Text(label) } },
        dismissButton = { TextButton(onClick = { open = false }) { Text(stringResource(R.string.fork_close)) } })
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
                    api?.errorCode in setOf("device_cleanup_incomplete", "deletion_cleanup_failed") -> api?.message ?: stringResource(R.string.fork_failed)
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
