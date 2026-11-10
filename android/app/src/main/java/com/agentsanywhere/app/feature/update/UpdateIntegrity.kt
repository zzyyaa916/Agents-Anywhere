package com.agentsanywhere.app.feature.update

import java.io.File
import java.security.MessageDigest

internal fun verifyUpdateChecksum(file: File, expected: String) {
    require(Regex("[a-f0-9]{64}").matches(expected)) { "Invalid update checksum." }
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            digest.update(buffer, 0, count)
        }
    }
    require(digest.digest().joinToString("") { "%02x".format(it) } == expected) { "Update checksum mismatch." }
}
