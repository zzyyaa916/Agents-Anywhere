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
    @Test fun lowReminderRequiresMatchingRuntimeFreshFiveHourWindow() {
        val now = Instant.parse("2026-11-10T00:00:00Z")
        val future = "2026-11-10T01:00:00Z"
        val a = UsageAccount("codex", "abc", false, null, listOf(UsageWindow("five_hour", 20.0, future, null), UsageWindow("seven_day", 0.0, future, null)))
        assertEquals(1, UsageCache(listOf(a), emptyList()).lowFiveHour("codex", now).size)
        assertTrue(UsageCache(listOf(a.copy(stale = true)), emptyList()).lowFiveHour("codex", now).isEmpty())
        assertTrue(UsageCache(listOf(a), emptyList()).lowFiveHour("claude_code", now).isEmpty())
        assertTrue(UsageCache(listOf(a), emptyList()).lowFiveHour("codex", Instant.parse("2026-11-10T02:00:00Z")).isEmpty())
    }
    @Test fun emptyCacheDoesNotInventUsage() {
        assertEquals(listOf("codex", "claude_code"), UsageCache.parse(JSONObject()).unavailable)
    }
    @Test fun manualUsageKeepsPerWindowSourceAgeAndServerCircuitState() {
        val cache = UsageCache.parse(JSONObject("""{"serverTime":"2033-05-18T03:33:20Z","refresh":{"status":"circuit","nextAllowedAt":"2033-05-19T00:00:00Z","completedAt":"2033-05-17T00:00:00Z","errorCode":"rate_limited"},"snapshots":[{"runtime":"claude_code","accountLabel":"abc","stale":false,"windows":[{"kind":"five_hour","remainingPercent":29,"resetsAt":"2026-11-09T00:00:00Z","source":"event","ageSeconds":720},{"kind":"seven_day","remainingPercent":72,"resetsAt":"2026-11-09T00:00:00Z","source":"probe","ageSeconds":3000}]}]}"""))
        assertEquals("2033-05-18T03:33:20Z", cache.serverTime)
        assertEquals("circuit", cache.refresh.status)
        assertEquals("2033-05-19T00:00:00Z", cache.refresh.nextAllowedAt)
        assertEquals("2033-05-17T00:00:00Z", cache.refresh.completedAt)
        assertEquals("rate_limited", cache.refresh.errorCode)
        val windows = cache.accounts.single().windows
        assertEquals(listOf("event", "probe"), windows.map { it.source })
        assertEquals(listOf(720.0, 3000.0), windows.map { it.ageSeconds })
        assertEquals(listOf(29.0, 72.0), windows.map { it.remaining })
    }
}
