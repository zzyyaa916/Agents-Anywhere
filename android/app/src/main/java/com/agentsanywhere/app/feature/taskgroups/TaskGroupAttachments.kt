package com.agentsanywhere.app.feature.taskgroups

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.agentsanywhere.app.feature.sessions.NewSessionAttachmentPart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

suspend fun readTaskGroupAttachments(context: Context, uris: List<Uri>): List<NewSessionAttachmentPart> = withContext(Dispatchers.IO) {
    require(uris.size <= 10) { "最多选择 10 个附件" }
    uris.map { uri ->
        val name = context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        } ?: uri.lastPathSegment ?: "附件"
        val bytes = requireNotNull(context.contentResolver.openInputStream(uri)) { "无法读取附件：$name" }.use { input ->
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (output.size() <= 25 * 1024 * 1024) {
                val count = input.read(buffer, 0, minOf(buffer.size, 25 * 1024 * 1024 + 1 - output.size()))
                if (count < 0) break
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        require(bytes.isNotEmpty() && bytes.size <= 25 * 1024 * 1024) { "附件不能为空且不能超过 25 MB：$name" }
        NewSessionAttachmentPart(name, context.contentResolver.getType(uri) ?: "application/octet-stream", bytes)
    }
}

fun retainTaskGroupAttachments(context: Context, uris: List<Uri>): List<String> {
    require(uris.size <= 10) { "最多选择 10 个附件" }
    return uris.map { uri ->
        try { context.contentResolver.takePersistableUriPermission(uri, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        catch (_: SecurityException) { /* Some providers only grant access for the current app session. */ }
        uri.toString()
    }
}
