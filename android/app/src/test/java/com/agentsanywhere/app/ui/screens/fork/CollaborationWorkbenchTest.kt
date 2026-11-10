package com.agentsanywhere.app.ui.screens.fork

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.agentsanywhere.app.api.*
import com.agentsanywhere.app.feature.auth.AuthSessionReader
import com.agentsanywhere.app.feature.devices.DeviceRuntimeList
import com.agentsanywhere.app.feature.taskgroups.TaskGroupsController
import com.agentsanywhere.app.model.AgentProject
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class CollaborationWorkbenchTest {
    @get:Rule val compose = createComposeRule()
    @Test fun nativePanesRegisterIndependentQueuesAndRetryOnlyFailedTargets() {
        MockWebServer().use { server ->
            val group = """{"id":"group-1","projectId":"project-1","phase":"ready","request":{"content":"恢复原生任务","candidates":[{"runtime":"custom","runtimeId":"one"},{"runtime":"other","runtimeId":"two"}]},"candidates":[{"phase":"sent","sessionId":"session-1"},{"phase":"sent","sessionId":"session-2"}]}"""
            server.dispatcher = object : okhttp3.mockwebserver.Dispatcher() {
                override fun dispatch(request: okhttp3.mockwebserver.RecordedRequest) = MockResponse().setBody("""{"groups":[$group]}""")
            }
            val auth = object : AuthSessionReader {
                override fun readServerUrl() = server.url("/").toString()
                override fun readAccessToken() = "synthetic"
            }
            val project = AgentProject("project-1", "user", "device", "原生项目", "/repo", false, null, 0, null, "now", "now")
            val delivered = mutableListOf<Pair<String, String>>()
            var secondReady = false
            compose.setContent {
                MaterialTheme {
                    CollaborationWorkbench(project, TaskGroupsController(TaskGroupsApi(ApiClient()), auth),
                        onListRuntimes = { Result.success(DeviceRuntimeList("device", emptyList(), null)) },
                        onLoadCapabilities = { _, _ -> error("No catalog requested") },
                        onLoadModels = { _, _ -> error("No catalog requested") },
                        onLoadPermissions = { _, _ -> error("No catalog requested") }, onClose = {},
                    ) { session, ready, _ ->
                        DisposableEffect(session) {
                            ready { text ->
                                if (session == "session-2" && !secondReady) false else { delivered.add(session to text); true }
                            }
                            onDispose { ready(null) }
                        }
                        Text("原生会话 $session")
                    }
                }
            }
            compose.waitUntil(10000) { compose.onAllNodesWithText("恢复原生任务").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText("恢复原生任务").performClick()
            compose.waitUntil(10000) { compose.onAllNodesWithText("原生会话 session-1").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithTag("task-unified-input").performTextInput("统一任务")
            compose.onNodeWithText("发送", useUnmergedTree = true).performClick()
            compose.runOnIdle { assertEquals(listOf("session-1" to "统一任务"), delivered); secondReady = true }
            compose.onNodeWithText("发送", useUnmergedTree = true).performClick()
            compose.runOnIdle { assertEquals(listOf("session-1" to "统一任务", "session-2" to "统一任务"), delivered) }
        }
    }
}
