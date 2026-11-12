package com.agentsanywhere.app.ui.designsystem

import androidx.compose.material3.SnackbarDuration
import org.junit.Assert.*
import org.junit.Test

class AAToastVisualsTest {
    @Test fun longErrorKeepsFullMessageAndUsesAccessibleSnackbarTimeout() {
        val message = "错误详情\n".repeat(200)
        val visuals = AAToastVisuals(message = message, isError = true)
        assertEquals(message, visuals.message)
        assertNull(visuals.timeoutMillis)
        assertEquals(SnackbarDuration.Long, visuals.duration)
    }
    @Test fun ordinarySuccessKeepsExistingShortTimeout() {
        assertEquals(1600L, AAToastVisuals(message = "完成").timeoutMillis)
    }
}
