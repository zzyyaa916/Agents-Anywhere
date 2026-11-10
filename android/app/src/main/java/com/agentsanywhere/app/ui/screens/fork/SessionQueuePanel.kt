package com.agentsanywhere.app.ui.screens.fork

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.agentsanywhere.app.R
import com.agentsanywhere.app.feature.sessiondetail.QueuedSessionMessage

@Composable
fun SessionQueuePanel(items: List<QueuedSessionMessage>, paused: Boolean, canSend: Boolean, canSteer: Boolean,
                      onPause: () -> Unit, onResume: () -> Unit, onRemove: (String) -> Unit, onSend: (String, Boolean) -> Unit) {
    if (items.isEmpty()) return
    Surface(tonalElevation = 3.dp) {
        Column(Modifier.fillMaxWidth().heightIn(max = 220.dp).padding(horizontal = 16.dp).verticalScroll(rememberScrollState())) {
            Row {
                Text(stringResource(R.string.fork_queue), Modifier.weight(1f).padding(top = 12.dp))
                TextButton(onClick = if (paused) onResume else onPause) { Text(stringResource(if (paused) R.string.fork_queue_resume else R.string.fork_queue_pause)) }
            }
            items.forEachIndexed { index, item ->
                Text(item.text, maxLines = 3)
                item.attachments.forEach { Text(it.name, style = MaterialTheme.typography.bodySmall) }
                if (item.status == "failed") Text(stringResource(R.string.fork_queue_failed), color = MaterialTheme.colorScheme.error)
                if (item.status == "sending") Text(stringResource(R.string.fork_queue_sending))
                Row {
                    if (canSend && index == 0) TextButton(onClick = { onSend(item.id, false) }, enabled = item.status != "sending") { Text(stringResource(R.string.fork_queue_send)) }
                    if (canSteer) TextButton(onClick = { onSend(item.id, true) }, enabled = item.status != "sending") { Text(stringResource(R.string.fork_queue_steer)) }
                    TextButton(onClick = { onRemove(item.id) }, enabled = item.status != "sending") { Text(stringResource(R.string.fork_queue_remove)) }
                }
            }
        }
    }
}
