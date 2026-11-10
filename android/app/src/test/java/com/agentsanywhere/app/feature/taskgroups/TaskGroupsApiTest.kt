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
    @Test fun chainRetainsAllAncestorsAndForwardedDescendants() {
        val root = TaskGroup.parse(JSONObject(group)).copy(id = "root", sourceId = null)
        val child = root.copy(id = "child", sourceId = "root")
        val grandchild = root.copy(id = "grandchild", sourceId = "child")
        val unrelated = root.copy(id = "unrelated")
        assertEquals(setOf("root", "child", "grandchild"), taskGroupChain(listOf(grandchild, unrelated, child, root), "grandchild"))
        assertEquals(listOf("root", "child", "grandchild"), taskGroupChain(listOf(grandchild, child, root), "grandchild").toList())
        assertTrue(taskGroupChain(listOf(root), null).isEmpty())
    }
    @Test fun initialAttachmentsAreIncludedForEveryCandidateWithStableOperation() = kotlinx.coroutines.runBlocking {
        MockWebServer().use { server ->
            val runtime = runtime("custom-1", "自定义 AI")
            val inventory = DeviceRuntimeList("device", listOf(runtime), null)
            var config = com.agentsanywhere.app.feature.sessions.NewSessionRuntimeSelectionState().beginRuntimeInventory("device").replaceRuntimeInventory(inventory, runtime.id).beginRuntimeDetails()
            val capability = com.agentsanywhere.app.feature.sessions.NewSessionRuntimeCapability("runtime.attachment", "1", "runtime", "custom-1", null, true, true, true, null, emptyMap())
            config = config.applyCapabilities(requireNotNull(config.requestKey), com.agentsanywhere.app.feature.sessions.NewSessionRuntimeCapabilities("device", 1L, listOf(capability), null))
            val auth = object : com.agentsanywhere.app.feature.auth.AuthSessionReader {
                override fun readServerUrl() = server.url("/").toString()
                override fun readAccessToken() = "synthetic"
            }
            val controller = TaskGroupsController(TaskGroupsApi(ApiClient()), auth)
            repeat(2) {
                server.enqueue(MockResponse().setBody(group))
                assertTrue(controller.create("same-operation", "project-1", "任务", listOf(config, config), listOf(com.agentsanywhere.app.feature.sessions.NewSessionAttachmentPart("file.txt", "text/plain", "payload".toByteArray()))).isSuccess)
                val body = JSONObject(server.takeRequest().body.readUtf8())
                assertEquals("same-operation", body.getString("operationId"))
                assertEquals(2, body.getJSONArray("candidates").length())
                val attachment = body.getJSONArray("attachments").getJSONObject(0)
                assertEquals("payload", String(java.util.Base64.getDecoder().decode(attachment.getString("contentBase64"))))
                assertEquals(64, attachment.getString("sha256").length)
            }
            val large = ByteArray(13 * 1024 * 1024)
            assertTrue(controller.create("large-operation", "project-1", "任务", listOf(config), listOf(
                com.agentsanywhere.app.feature.sessions.NewSessionAttachmentPart("one", "text/plain", large),
                com.agentsanywhere.app.feature.sessions.NewSessionAttachmentPart("two", "text/plain", large),
            )).isFailure)
            assertEquals(2, server.requestCount)
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
        assertEquals("custom-1", parseForwardCommand("转发给 我的 AI", agents)?.runtimeId)
        assertEquals("继续执行", parseForwardCommand("转发给 Claude Code 继续执行", agents)?.instructions)
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
