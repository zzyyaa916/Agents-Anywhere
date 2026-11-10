package com.agentsanywhere.app.feature.fork

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class ForkUsageTest {
    @Test fun quotaWaitResumesOnlyAfterKnownDeadline() {
        val now = Instant.parse("2026-11-10T00:00:00Z")
        assertTrue(QuotaWait("limited", null).waiting(now))
        assertTrue(QuotaWait("limited", "2026-11-10T01:00:00Z").waiting(now))
        assertFalse(QuotaWait("limited", "2026-11-09T23:59:59Z").waiting(now))
        assertFalse(QuotaWait("stopped", null).waiting(now))
    }
    @Test fun rejectsInvalidPercentagesAndKeepsExpiredValuesMarkedExpired() {
        val cache = UsageCache.parse(JSONObject("""{"snapshots":[{"runtime":"claude_code","accountLabel":"abc","stale":false,"windows":[{"kind":"five_hour","remainingPercent":101,"resetsAt":"2026-11-09T00:00:00Z"},{"kind":"seven_day","remainingPercent":12,"resetsAt":"2026-11-09T00:00:00Z"}]}]}"""))
        assertEquals(1, cache.accounts.single().windows.size)
        assertTrue(cache.accounts.single().windows.single().expired(Instant.parse("2026-11-10T00:00:00Z")))
        assertEquals(12.0, cache.accounts.single().windows.single().remaining, 0.0)
        assertEquals(listOf("codex"), cache.unavailable)
    }
    @Test fun emptyCacheDoesNotInventUsage() {
        assertEquals(listOf("codex", "claude_code"), UsageCache.parse(JSONObject()).unavailable)
    }
}
