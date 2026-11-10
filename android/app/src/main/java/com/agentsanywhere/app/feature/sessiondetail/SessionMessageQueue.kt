package com.agentsanywhere.app.feature.sessiondetail

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

// Only uploaded attachment references are persisted, never file bytes or account credentials.
data class QueuedSessionMessage(val id: String, val text: String, val attachments: List<TimelineAttachment>, val status: String = "queued")
class SessionMessageQueue(private val preferences: SharedPreferences, private val key: String) {
    constructor(context: Context, scope: String, sessionId: String) : this(
        context.getSharedPreferences("fork-message-queues", Context.MODE_PRIVATE),
        JSONArray(listOf(scope, sessionId)).toString(),
    )
    var messages: List<QueuedSessionMessage> = restore()
        private set
    var paused: Boolean = messages.isNotEmpty()
        private set

    private fun restore(): List<QueuedSessionMessage> = runCatching {
        val items = JSONArray(preferences.getString(key, "[]"))
        (0 until items.length()).map { index ->
            val item = items.getJSONObject(index)
            val refs = item.getJSONArray("attachments")
            QueuedSessionMessage(item.getString("id"), item.getString("text"), (0 until refs.length()).map { i ->
                val file = refs.getJSONObject(i)
                TimelineAttachment(file.getString("fileId"), file.getString("name"), file.getString("mediaType"), file.getLong("size"))
            }, if (item.optString("status") == "sending") "failed" else item.optString("status", "queued"))
        }
    }.getOrDefault(emptyList())

    private fun persist(items: List<QueuedSessionMessage>): Boolean = runCatching {
        val json = JSONArray(items.map { item -> JSONObject().put("id", item.id).put("text", item.text).put("status", item.status)
            .put("attachments", JSONArray(item.attachments.map { file -> JSONObject().put("fileId", file.fileId).put("name", file.name).put("mediaType", file.mediaType).put("size", file.size) })) })
        preferences.edit().putString(key, json.toString()).commit()
    }.getOrDefault(false)

    fun enqueue(text: String, attachments: List<TimelineAttachment>): Boolean {
        if (text.isBlank() && attachments.isEmpty()) return false
        val next = messages + QueuedSessionMessage("opt_${UUID.randomUUID()}", text, attachments.map { it.copy(localPreviewUri = null) })
        if (!persist(next)) return false
        messages = next
        return true
    }
    fun pause() { paused = true }
    fun resume() { paused = false }
    fun remove(id: String): Boolean {
        if (messages.any { it.id == id && it.status == "sending" } || synchronized(active) { active[key] == id }) return false
        val next = messages.filterNot { it.id == id }
        if (!persist(next)) return false
        messages = next
        return true
    }
    fun begin(id: String): QueuedSessionMessage? = synchronized(active) {
        if (key in active) return null
        val item = messages.find { it.id == id && it.status != "sending" } ?: return null
        val next = messages.map { if (it.id == id) it.copy(status = "sending") else it }
        if (!persist(next)) return null
        active[key] = id
        messages = next
        item
    }
    fun finish(id: String, accepted: Boolean) = synchronized(active) {
        val next = if (accepted) messages.filterNot { it.id == id } else messages.map { if (it.id == id) it.copy(status = "failed") else it }
        val saved = persist(next)
        messages = next
        if (!accepted || !saved) paused = true
        active.remove(key)
    }
    companion object { private val active = mutableMapOf<String, String>() }
}
