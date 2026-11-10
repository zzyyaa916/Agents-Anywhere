package com.agentsanywhere.app.feature.fork

import com.agentsanywhere.app.api.ForkApi
import com.agentsanywhere.app.feature.auth.AuthSessionReader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.Instant

class ForkController(private val api: ForkApi, private val auth: AuthSessionReader) {
    val scopeKey: String get() = JSONObject().put("server", auth.readServerUrl()).put("user", auth.readUserId()).toString()
    private suspend fun <T> request(action: (String, String) -> T): Result<T> = withContext(Dispatchers.IO) {
        runCatching {
            val server = auth.readServerUrl()
            val token = auth.readAccessToken()
            check(server.isNotBlank() && token.isNotBlank())
            action(server, token)
        }
    }
    val taskGroups = com.agentsanywhere.app.feature.taskgroups.TaskGroupsController(api.taskGroups, auth)
    suspend fun usage(refresh: Boolean = false) = request { s, t -> UsageCache.parse(api.usage(s, t, refresh)) }
    suspend fun deletionCount(id: String) = request { s, t -> api.deletionCount(s, t, id) }
    suspend fun deleteSession(id: String) = request { s, t -> api.deleteSession(s, t, id) }
    suspend fun deleteProject(id: String, count: Int) = request { s, t -> api.deleteProject(s, t, id, count) }
    suspend fun quota(id: String, recheck: Boolean = false) = request { s, t -> api.quota(s, t, id, recheck)?.let(QuotaWait::parse) }
}

data class UsageWindow(val kind: String, val remaining: Double, val resetsAt: String, val model: String?) {
    fun expired(now: Instant = Instant.now()): Boolean = runCatching { !Instant.parse(resetsAt).isAfter(now) }.getOrDefault(true)
}
data class UsageAccount(val runtime: String, val label: String, val stale: Boolean, val fetchedAt: String?, val windows: List<UsageWindow>)
data class UsageCache(val accounts: List<UsageAccount>, val unavailable: List<String>) {
    fun lowFiveHour(runtime: String?, now: Instant = Instant.now()): List<Pair<UsageAccount, UsageWindow>> = accounts
        .filter { it.runtime == runtime && !it.stale }
        .flatMap { account -> account.windows.filter { it.kind == "five_hour" && it.remaining <= 20 && !it.expired(now) }.map { account to it } }
    companion object {
        fun parse(value: JSONObject): UsageCache {
            val snapshots = value.optJSONArray("snapshots")
            val accounts = (0 until (snapshots?.length() ?: 0)).mapNotNull { i ->
                val account = snapshots?.optJSONObject(i) ?: return@mapNotNull null
                val runtime = account.optString("runtime")
                if (runtime !in listOf("codex", "claude_code")) return@mapNotNull null
                val windows = account.optJSONArray("windows")
                UsageAccount(runtime, account.optString("accountKey").takeIf { it.matches(Regex("[a-f0-9]{64}")) }?.take(7) ?: "—", account.optBoolean("stale", true),
                    account.optString("fetchedAt").takeUnless { it.isBlank() || it == "null" },
                    (0 until (windows?.length() ?: 0)).mapNotNull { n ->
                        val w = windows?.optJSONObject(n) ?: return@mapNotNull null
                        val percent = w.optDouble("remainingPercent", Double.NaN)
                        val reset = w.optString("resetsAt")
                        if (!percent.isFinite() || percent !in 0.0..100.0 || runCatching { Instant.parse(reset) }.isFailure) null
                        else UsageWindow(w.optString("kind"), percent, reset, w.optString("modelScope").takeUnless { it.isBlank() || it == "null" })
                    })
            }
            val unavailable = listOf("codex", "claude_code").filter { runtime -> accounts.none { it.runtime == runtime } }
            return UsageCache(accounts, unavailable)
        }
    }
}
data class QuotaWait(val state: String, val resetsAt: String?) {
    fun waiting(now: Instant = Instant.now()): Boolean = state == "limited" &&
        (resetsAt == null || runCatching { Instant.parse(resetsAt).isAfter(now) }.getOrDefault(true))
    companion object {
        fun parse(value: JSONObject) = QuotaWait(value.optString("state"), value.optString("resetsAt").takeUnless { it.isBlank() || it == "null" })
    }
}

