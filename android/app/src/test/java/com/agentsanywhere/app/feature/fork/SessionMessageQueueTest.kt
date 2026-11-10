package com.agentsanywhere.app.feature.fork

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.agentsanywhere.app.feature.sessiondetail.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class SessionMessageQueueTest {
    private fun prefs() = ApplicationProvider.getApplicationContext<Context>().getSharedPreferences(java.util.UUID.randomUUID().toString(), 0)
    @Test fun restoredQueueIsPausedAndInFlightBecomesUnknownWithoutChangingId() {
        val prefs = prefs(); val queue = SessionMessageQueue(prefs, "server/user/session")
        assertTrue(queue.enqueue("hello", emptyList())); val id = queue.messages.single().id
        assertNotNull(queue.begin(id)); assertNull(queue.begin(id))
        val restored = SessionMessageQueue(prefs, "server/user/session")
        assertTrue(restored.paused); assertEquals("failed", restored.messages.single().status); assertEquals(id, restored.messages.single().id)
        queue.finish(id, false)
    }
    @Test fun keepsFailuresAndRemovesAcceptedMessagesInOrder() {
        val queue = SessionMessageQueue(prefs(), "fifo")
        queue.enqueue("one", emptyList()); queue.enqueue("two", emptyList())
        val id = queue.messages.first().id; queue.begin(id); queue.finish(id, false)
        assertTrue(queue.paused); assertEquals("failed", queue.messages.first().status)
        queue.begin(id); queue.finish(id, true)
        assertEquals("two", queue.messages.single().text)
    }
    @Test fun scopesAndAttachmentReferencesStaySeparate() {
        val prefs = prefs(); val queue = SessionMessageQueue(prefs, "a/user/session")
        queue.enqueue("file", listOf(TimelineAttachment("file_1", "a.txt", "text/plain", 10, localPreviewUri="file:///secret")))
        val restored = SessionMessageQueue(prefs, "a/user/session")
        assertEquals("file_1", restored.messages.single().attachments.single().fileId)
        assertNull(restored.messages.single().attachments.single().localPreviewUri)
        assertTrue(SessionMessageQueue(prefs, "b/user/session").messages.isEmpty())
        assertFalse(prefs.getString("a/user/session", "")!!.contains("secret"))
    }
}
