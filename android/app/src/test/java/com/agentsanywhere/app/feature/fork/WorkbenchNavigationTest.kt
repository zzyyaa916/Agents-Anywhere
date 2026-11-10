package com.agentsanywhere.app.feature.fork

import org.junit.Assert.*
import org.junit.Test

class WorkbenchNavigationTest {
    @Test fun confinesNavigationToAuthenticatedOrigin() {
        val origin = "https://example.com:9443"
        assertTrue(workbenchAllowsNavigation(origin, "$origin/?project=p#session"))
        assertTrue(workbenchAllowsNavigation(origin, "$origin/files/a?token=x"))
        listOf("https://example.com.evil.test:9443/", "http://example.com:9443", "https://example.com", "https://user@example.com:9443", "javascript:alert(1)", "file:///tmp/a").forEach {
            assertFalse(it, workbenchAllowsNavigation(origin, it))
        }
    }
}
