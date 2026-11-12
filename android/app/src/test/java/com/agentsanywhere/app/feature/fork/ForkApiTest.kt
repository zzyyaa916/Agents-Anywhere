package com.agentsanywhere.app.feature.fork

import com.agentsanywhere.app.api.*
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class ForkApiTest {
    @Test fun projectDeletionUsesExactPreviewCountAndEncodedId() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"sessionCount":123}""")); server.enqueue(MockResponse().setBody("{}"))
            val api = ForkApi(ApiClient()); val url = server.url("/").toString()
            val count = api.deletionCount(url, "synthetic", "project a")
            assertEquals(123, count); assertEquals("GET", server.takeRequest().method)
            api.deleteProject(url, "synthetic", "project a", count)
            val request = server.takeRequest(); assertEquals("DELETE", request.method)
            assertTrue(request.path!!.contains("/contents?")); assertTrue(request.path!!.contains("expectedSessionCount=123")); assertTrue(request.path!!.contains("project%20a") || request.path!!.contains("project+a"))
        }
    }
    @Test fun sessionDeletionHandles204AndBusyIds() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(204))
            val api = ForkApi(ApiClient()); val url = server.url("/").toString()
            api.deleteSession(url, "synthetic", "sess_1"); assertEquals("/api/v2/sessions/sess_1/contents", server.takeRequest().path)
            server.enqueue(MockResponse().setResponseCode(409).setHeader("Content-Type", "application/json").setBody("""{"detail":{"code":"session_running","sessionIds":["sess_2"]}}"""))
            try { api.deleteSession(url, "synthetic", "sess_2"); fail("must reject busy deletion") } catch (error: ApiException) {
                assertEquals(409, error.statusCode); assertEquals(listOf("sess_2"), error.blockingSessionIds)
            }
        }
    }
    @Test fun cleanupAbandonmentUsesExplicitPost() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(204))
            ForkApi(ApiClient()).abandonCleanup(server.url("/").toString(), "synthetic", "project a", true)
            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertTrue(request.path!!.endsWith("/contents/abandon"))
        }
    }
    @Test fun usageAndQuotaUseOnlyServerCacheRoutes() {
        MockWebServer().use { server ->
            val api = ForkApi(ApiClient()); val url = server.url("/").toString()
            server.enqueue(MockResponse().setBody("{}")); api.usage(url, "synthetic", false)
            assertEquals("/api/v2/account-usage", server.takeRequest().path)
            server.enqueue(MockResponse().setBody("{}")); api.quota(url, "synthetic", "sess_1", true)
            val request = server.takeRequest(); assertEquals("POST", request.method); assertEquals("/api/v2/sessions/sess_1/quota/recheck", request.path)
        }
    }
    @Test fun steerKeepsClientIdAndChecksNestedRejection() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("""{"ok":true,"result":{"ok":false}}"""))
            val result = SessionsApi(ApiClient()).sendSessionMessage(server.url("/").toString(), "synthetic", "sess_1", "extra", "stable_id", steer = true)
            assertFalse(result.ok)
            val request = server.takeRequest(); assertEquals("/api/v2/sessions/sess_1/runtime/steer", request.path)
            assertEquals("stable_id", org.json.JSONObject(request.body.readUtf8()).getString("clientMessageId"))
        }
    }
}
