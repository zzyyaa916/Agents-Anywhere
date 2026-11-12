package com.agentsanywhere.app.api

import org.json.JSONObject

class ForkApi(private val client: ApiClient) {
    val taskGroups = TaskGroupsApi(client)
    fun usage(server: String, token: String, refresh: Boolean): JSONObject =
        if (refresh) client.postJson(server, "/account-usage/refresh", JSONObject(), token)
        else client.getJson(server, "/account-usage", token)

    fun deletionCount(server: String, token: String, project: String): Int =
        client.getJson(server, "/projects/${project.urlEncode()}/deletion-preview", token).getInt("sessionCount")

    fun abandonCleanup(server: String, token: String, id: String, project: Boolean) {
        client.postJson(server, "/${if (project) "projects" else "sessions"}/${id.urlEncode()}/contents/abandon", JSONObject(), token)
    }

    fun deleteSession(server: String, token: String, id: String) {
        client.deleteJson(server, "/sessions/${id.urlEncode()}/contents", token)
    }

    fun deleteProject(server: String, token: String, id: String, count: Int) {
        client.deleteJson(server, "/projects/${id.urlEncode()}/contents?expectedSessionCount=$count", token)
    }

    fun quota(server: String, token: String, id: String, recheck: Boolean): JSONObject? =
        (if (recheck) client.postJson(server, "/sessions/${id.urlEncode()}/quota/recheck", JSONObject(), token)
        else client.getJson(server, "/sessions/${id.urlEncode()}/quota", token)).optJSONObject("quotaLimit")
}
