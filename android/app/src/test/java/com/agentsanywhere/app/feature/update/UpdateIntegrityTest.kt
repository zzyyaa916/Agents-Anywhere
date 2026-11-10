package com.agentsanywhere.app.feature.update

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class UpdateIntegrityTest {
    @Test fun verifiesPublishedChecksumAndRejectsChangedFiles() {
        val file = File.createTempFile("aa-update", ".apk")
        try {
            file.writeText("abc")
            val hash = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
            verifyUpdateChecksum(file, hash)
            file.writeText("abcd")
            assertThrows(IllegalArgumentException::class.java) { verifyUpdateChecksum(file, hash) }
            assertThrows(IllegalArgumentException::class.java) { verifyUpdateChecksum(file, "invalid") }
        } finally { file.delete() }
    }
}
