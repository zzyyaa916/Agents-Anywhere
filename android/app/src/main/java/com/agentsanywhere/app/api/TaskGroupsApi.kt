package com.agentsanywhere.app.api

import org.json.JSONArray
import org.json.JSONObject

data class TaskGroupCandidate(val slot: Int, val phase: String, val sessionId: String?, val runtimeId: String, val error: String?)
data class TaskGroup(val id: String, val projectId: String, val content: String, val phase: String, val sourceId: String?, val candidates: List<TaskGroupCandidate>) {
    companion object {
        fun parse(value: JSONObject): TaskGroup {
            val request = value.getJSONObject("request")
            val configs = request.getJSONArray("candidates")
            val candidates = value.getJSONArray("candidates")
            return TaskGroup(value.getString("id"), value.getString("projectId"), request.optString("content"), value.getString("phase"),
                request.optJSONObject("source")?.optString("groupId"),
                (0 until candidates.length()).map { slot ->
                    val item = candidates.getJSONObject(slot)
                    TaskGroupCandidate(slot, item.getString("phase"), item.optString("sessionId").takeUnless { it.isBlank() || it == "null" },
                        configs.getJSONObject(slot).getString("runtimeId"), item.optString("error").takeUnless { it.isBlank() || it == "null" })
                })
        }
    }
}

class TaskGroupsApi(private val client: ApiClient) {
    fun list(server: String, token: String, projectId: String): List<TaskGroup> {
        val result = client.getJson(server, "/task-groups?projectId=${projectId.urlEncode()}", token).getJSONArray("groups")
        return (0 until result.length()).map { TaskGroup.parse(result.getJSONObject(it)) }
    }
    fun get(server: String, token: String, id: String): TaskGroup = TaskGroup.parse(client.getJson(server, "/task-groups/${id.urlEncode()}", token))
    fun create(server: String, token: String, body: JSONObject): TaskGroup = TaskGroup.parse(client.postJson(server, "/task-groups", body, token, readTimeoutSeconds = 120))
    fun start(server: String, token: String, id: String, slot: Int): TaskGroup = TaskGroup.parse(client.postJson(server, "/task-groups/${id.urlEncode()}/candidates/$slot/start", JSONObject(), token, readTimeoutSeconds = 120))
    fun handoff(server: String, token: String, id: String, body: JSONObject): TaskGroup = TaskGroup.parse(client.postJson(server, "/task-groups/${id.urlEncode()}/handoffs", body, token, readTimeoutSeconds = 120))
}
