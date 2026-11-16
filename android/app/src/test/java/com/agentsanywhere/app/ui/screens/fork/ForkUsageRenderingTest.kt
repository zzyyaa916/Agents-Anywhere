package com.agentsanywhere.app.ui.screens.fork

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.agentsanywhere.app.api.ApiClient
import com.agentsanywhere.app.api.ForkApi
import com.agentsanywhere.app.feature.auth.AuthSessionReader
import com.agentsanywhere.app.feature.fork.ForkController
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ForkUsageRenderingTest {
    @get:Rule val compose = createComposeRule()

    @Test fun inactiveFiveHourRemainsVisibleAlongsideSevenDay() = renderWindow("null")
    @Test fun epochSentinelDoesNotHideFiveHourOrRender1970() = renderWindow("0")

    private fun renderWindow(reset: String) {
        MockWebServer().use { server ->
            server.dispatcher = object : okhttp3.mockwebserver.Dispatcher() {
                override fun dispatch(request: okhttp3.mockwebserver.RecordedRequest) = MockResponse().setBody(
                    """{"snapshots":[{"runtime":"claude_code","accountLabel":"test","windows":[{"kind":"five_hour","remainingPercent":100,"resetsAt":$reset},{"kind":"seven_day","remainingPercent":55,"resetsAt":"2026-11-19T17:00:00Z"}]}]}"""
                )
            }
            val auth = object : AuthSessionReader {
                override fun readServerUrl() = server.url("/").toString()
                override fun readAccessToken() = "synthetic"
            }
            val controller = ForkController(ForkApi(ApiClient()), auth)
            compose.setContent { MaterialTheme { ForkUsageButton(controller) } }
            compose.onNodeWithContentDescription("账号用量").performClick()
            compose.waitUntil(10000) { compose.onAllNodesWithText("剩余 100%").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText("剩余 100%").assertIsDisplayed()
            compose.onNodeWithText("剩余 55%").assertIsDisplayed()
            compose.onNodeWithText("重置时间：—").assertIsDisplayed()
            compose.onAllNodesWithText("01/01", substring = true).assertCountEquals(0)
        }
    }
}
