package com.agentsanywhere.app.feature.fork

import com.agentsanywhere.app.api.parseForkAndroidRelease
import org.json.JSONArray
import org.junit.Assert.*
import org.junit.Test

class ForkUpdatesTest {
    @Test fun onlyMatchingForkApkCanBeOffered() {
        val releases = JSONArray("""[{"tag_name":"v2.5.5-fork","assets":[{"name":"official.apk","browser_download_url":"https://example.com/official.apk"},{"name":"Agents.Anywhere.Fork.apk","browser_download_url":"https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v2.5.5-fork/Agents.Anywhere.Fork.apk"}]}]""")
        assertEquals("2.5.5", parseForkAndroidRelease(releases, "2.5.4")!!.versionName)
        assertNull(parseForkAndroidRelease(releases, "2.5.5"))
        releases.getJSONObject(0).getJSONArray("assets").getJSONObject(1).put("browser_download_url", "https://example.com/app.apk")
        assertNull(parseForkAndroidRelease(releases, "2.5.4"))
    }
}
