package com.agentsanywhere.app.feature.taskgroups

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class JointConversationState(
    val projectId: String = "", val sessions: List<String> = emptyList(),
    val draft: String = "", val excluded: Set<String> = emptySet(), val hidden: Set<String> = emptySet(),
)

class JointConversationStore(context: Context, scope: String) {
    private val preferences = context.applicationContext.getSharedPreferences("fork-joint-conversations", Context.MODE_PRIVATE)
    private val key = "v1:$scope"
    fun read(): JointConversationState = decodeJointState(preferences.getString(key, null))
    fun save(state: JointConversationState) { preferences.edit().putString(key, encodeJointState(state)).apply() }
}

internal fun encodeJointState(state: JointConversationState): String = JSONObject()
    .put("projectId", state.projectId).put("sessions", JSONArray(state.sessions))
    .put("draft", state.draft).put("excluded", JSONArray(state.excluded.toList())).put("hidden", JSONArray(state.hidden.toList())).toString()

internal fun decodeJointState(raw: String?): JointConversationState = runCatching {
    val value = JSONObject(raw ?: return JointConversationState())
    fun values(key: String): List<String> = value.optJSONArray(key)?.let { array ->
        (0 until array.length()).map { array.getString(it) }.distinct()
    }.orEmpty()
    JointConversationState(value.optString("projectId"), values("sessions").take(2), value.optString("draft"), values("excluded").toSet(), values("hidden").toSet())
}.getOrDefault(JointConversationState())
