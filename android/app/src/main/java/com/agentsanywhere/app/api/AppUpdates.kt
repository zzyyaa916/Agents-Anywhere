package com.agentsanywhere.app.api

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import java.net.URI
import java.util.concurrent.TimeUnit

data class AndroidAppRelease(val versionName: String, val downloadUrl: String)

class AppUpdatesApi {
    fun check(serverUrl: String, currentVersionName: String): AndroidAppRelease? {
        require(normalizeServerOrigin(serverUrl) != null)
        // Public release metadata never receives the user's AA authorization header.
        val request = Request.Builder().url("https://api.github.com/repos/zzyyaa916/Agents-Anywhere/releases?per_page=20")
            .header("Accept", "application/vnd.github+json").header("User-Agent", "Agents-Anywhere-Fork-Android").build()
        return client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw ApiException("Could not check Fork releases.", response.code)
            parseForkAndroidRelease(JSONArray(response.body?.string() ?: "[]"), currentVersionName)
        }
    }
    companion object {
        private val client = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).build()
    }
}

internal fun parseForkAndroidRelease(releases: JSONArray, current: String): AndroidAppRelease? {
    var latest: AndroidAppRelease? = null
    for (index in 0 until releases.length()) {
        val release = releases.optJSONObject(index) ?: continue
        val tag = release.optString("tag_name")
        if (release.optBoolean("draft") || !tag.endsWith("-fork")) continue
        val version = tag.removePrefix("v").removeSuffix("-fork")
        if ((compareUpdateVersions(version, current) ?: 0) <= 0) continue
        val assets = release.optJSONArray("assets") ?: continue
        for (n in 0 until assets.length()) {
            val asset = assets.optJSONObject(n) ?: continue
            if (asset.optString("name") != "Agents.Anywhere.Fork.apk") continue
            val url = asset.optString("browser_download_url")
            val uri = runCatching { URI(url) }.getOrNull() ?: continue
            if (uri.scheme != "https" || uri.host != "github.com" || uri.userInfo != null || !uri.path.startsWith("/zzyyaa916/Agents-Anywhere/releases/download/")) continue
            if (latest == null || (compareUpdateVersions(version, latest.versionName) ?: 0) > 0) latest = AndroidAppRelease(version, url)
        }
    }
    return latest
}
