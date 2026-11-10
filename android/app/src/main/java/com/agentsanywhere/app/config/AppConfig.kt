package com.agentsanywhere.app.config

import com.agentsanywhere.app.BuildConfig
import com.agentsanywhere.app.api.normalizeServerOrigin

object AppConfig {
    // Debug builds can override the backend in android/local.properties.
    val OFFICIAL_SERVER_URL: String = BuildConfig.OFFICIAL_SERVER_URL
    const val DESKTOP_DOWNLOAD_URL = "https://agents-anywhere.com/download"
    // Fork update discovery uses only matching signed APK assets on GitHub.
    const val UPDATE_DOWNLOAD_URL = "https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v2.5.7-fork/Agents.Anywhere.Fork.apk"

    fun isOfficialServer(serverUrl: String): Boolean {
        val officialOrigin = normalizeServerOrigin(OFFICIAL_SERVER_URL) ?: return false
        return normalizeServerOrigin(serverUrl) == officialOrigin
    }
}
