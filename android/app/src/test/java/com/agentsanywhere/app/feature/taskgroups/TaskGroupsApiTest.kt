package com.agentsanywhere.app.feature.taskgroups

import com.agentsanywhere.app.api.*
import com.agentsanywhere.app.feature.devices.*
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class TaskGroupsApiTest {
    private val group = """{"id":"group-1","projectId":"project-1","phase":"ready","request":{"content":"原始任务","candidates":[{"runtime":"custom","runtimeId":"custom-1","selections":{}}],"source":{"groupId":"origin-1"}},"candidates":[{"phase":"unknown","sessionId":"session-1","error":"timeout"}]}"""
    @Test fun restoreKeepsUnknownSessionAndForwardOrigin() {
        val parsed = TaskGroup.parse(JSONObject(group))
        assertEquals("origin-1", parsed.sourceId)
        assertEquals("unknown", parsed.candidates.single().phase)
        assertEquals("session-1", parsed.candidates.single().sessionId)
        assertEquals("custom-1", parsed.candidates.single().runtimeId)
    }
    @Test fun apiUsesNativeAuthenticatedRoutesWithoutImplicitStart() {
        MockWebServer().use { server ->
            val api = TaskGroupsApi(ApiClient()); val origin = server.url("/").toString()
            server.enqueue(MockResponse().setBody("""{"groups":[$group]}"""))
            assertEquals(1, api.list(origin, "synthetic", "project a").size)
            val list = server.takeRequest()
            assertEquals("GET", list.method); assertTrue(list.path!!.startsWith("/api/v2/task-groups?projectId=project"))
            assertEquals("Bearer synthetic", list.getHeader("Authorization"))
            server.enqueue(MockResponse().setBody(group))
            val body = JSONObject().put("operationId", "stable-op-123").put("instructions", "继续执行").put("attachments", org.json.JSONArray().put(JSONObject().put("fileId", "file-1")))
            api.handoff(origin, "synthetic", "group-1", body)
            val handoff = server.takeRequest()
            assertEquals("/api/v2/task-groups/group-1/handoffs", handoff.path)
            assertEquals("file-1", JSONObject(handoff.body.readUtf8()).getJSONArray("attachments").getJSONObject(0).getString("fileId"))
            assertEquals(2, server.requestCount)
            server.enqueue(MockResponse().setBody(group)); api.start(origin, "synthetic", "group-1", 0)
            assertEquals("/api/v2/task-groups/group-1/candidates/0/start", server.takeRequest().path)
        }
    }
    private fun runtime(id: String, name: String, type: String = id) = DeviceRuntime(
        connectorId = "device", id = id, type = type, displayName = name, present = true, configured = true, active = true,
        status = DeviceRuntimeStatus.Running, discovery = emptyMap(), schema = null, uiSchema = emptyMap(), config = null, error = null, lastDiscoveredAt = null, updatedAt = null,
    )
    @Test fun forwardSupportsEveryRuntimeAndMultilineInstructions() {
        val agents = listOf(runtime("custom-1", "我的 AI"), runtime("claude-1", "Claude Code", "claude_code"), runtime("codex-1", "Codex", "codex"))
        assertEquals(ForwardCommand("custom-1", "继续执行\n保留改动"), parseForwardCommand("转发给 我的 AI：继续执行\n保留改动", agents))
        assertEquals("claude-1", parseForwardCommand("转发给 Claude Code: 请审核代码", agents)?.runtimeId)
        assertEquals("codex-1", parseForwardCommand("转发给 CODEX：审核", agents)?.runtimeId)
        assertNull(parseForwardCommand("请解释转发功能", agents))
    }
    @Test fun missingOrAmbiguousAiDoesNotFallBackToSourceModel() {
        val agents = listOf(runtime("one", "同名"), runtime("two", "同名"))
        listOf("转发给 不存在：审核", "转发给 同名：审核").forEach { text ->
            try { parseForwardCommand(text, agents); fail("Must reject unsafe target") } catch (_: IllegalArgumentException) { }
        }
        assertEquals("one", parseForwardCommand("转发给 one：审核", agents)?.runtimeId)
    }
}
