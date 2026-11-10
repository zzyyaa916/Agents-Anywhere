package com.agentsanywhere.app.feature.fork

import android.content.Context
import org.robolectric.RuntimeEnvironment
import com.agentsanywhere.app.feature.sessiondetail.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class SessionMessageQueueTest {
    private fun prefs() = RuntimeEnvironment.getApplication().getSharedPreferences(java.util.UUID.randomUUID().toString(), 0)
    @Test fun storageFailureDoesNotAcceptOrClearDraft() {
        val backing = prefs()
        val blocked = object : android.content.SharedPreferences by backing {
            override fun edit(): android.content.SharedPreferences.Editor {
                val editor = backing.edit()
                return object : android.content.SharedPreferences.Editor by editor {
                    override fun putString(key: String?, value: String?): android.content.SharedPreferences.Editor {
                        editor.putString(key, value)
                        return this
                    }
                    override fun commit(): Boolean = false
                }
            }
        }
        val queue = SessionMessageQueue(blocked, "full")
        assertFalse(queue.enqueue("keep my draft", emptyList()))
        assertTrue(queue.messages.isEmpty())
    }
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
    @Test fun activeBusyQueueDoesNotBlockOtherSessions() {
        val prefs = prefs()
        val busy = SessionMessageQueue(prefs, "server/user/busy")
        val idle = SessionMessageQueue(prefs, "server/user/idle")
        busy.enqueue("first", emptyList()); val first = busy.messages.first().id
        assertNotNull(busy.begin(first))
        busy.enqueue("supplement", emptyList()); idle.enqueue("supplement", emptyList())
        assertNull(busy.begin(busy.messages.last().id))
        val idleId = idle.messages.single().id
        assertNotNull(idle.begin(idleId)); idle.finish(idleId, true)
        assertTrue(idle.messages.isEmpty())
        busy.finish(first, true)
        assertEquals("supplement", busy.messages.single().text)
        assertNotNull(busy.begin(busy.messages.single().id)); busy.finish(busy.messages.single().id, true)
        assertTrue(busy.messages.isEmpty())
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
