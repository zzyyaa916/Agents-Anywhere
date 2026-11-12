package com.agentsanywhere.app.feature.sessiondetail

import com.agentsanywhere.app.api.SessionsApi
import com.agentsanywhere.app.feature.auth.AuthSessionReader
import org.junit.Assert.assertEquals
import org.junit.Test

class OptimisticMessageOrderTest {
    @Test fun userMessageStaysBeforeStreamingReplyWhenEventCursorIsAheadOfTimelineOrder() {
        val controller = SessionDetailController(SessionsApi(), object : AuthSessionReader {
            override fun readServerUrl() = "https://test.invalid"
            override fun readAccessToken() = "test"
        })
        val old = TimelineMessage(id = "old", author = MessageAuthor.Agent, text = "old", orderSeq = 10, updatedSeq = 900)
        val state = SessionDetailState(timeline = SessionTimelineState(messages = listOf(old), nextSeq = 1000))
        val sent = controller.addOptimisticMessage("session", state, "question", "local-user")
        val reply = TimelineMessage(id = "reply", author = MessageAuthor.Agent, text = "reply", orderSeq = 12, updatedSeq = 1002)
        val duringStream = mergeOptimisticTimelineMessages(
            realMessages = listOf(old, reply), currentMessages = sent.messages,
            storedMessages = controller.optimisticMessages("session"), orderingItems = emptyList(),
        )
        assertEquals(listOf("old", "local-user", "reply"), duringStream.messages.map { it.id })
        val echo = TimelineMessage(id = "server-user", author = MessageAuthor.User, text = "question", orderSeq = 11, updatedSeq = 1003, clientMessageId = "local-user")
        val acknowledged = mergeOptimisticTimelineMessages(
            realMessages = listOf(old, echo, reply), currentMessages = duringStream.messages,
            storedMessages = controller.optimisticMessages("session"), orderingItems = emptyList(),
        )
        assertEquals(listOf("old", "server-user", "reply"), acknowledged.messages.map { it.id })
        assertEquals(0, acknowledged.pending.size)
    }
}
