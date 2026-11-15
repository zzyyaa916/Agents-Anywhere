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

    @Test fun userMessageStaysBeforeReplyAtCurrentTailUntilAcknowledged() {
        val controller = SessionDetailController(SessionsApi(), object : AuthSessionReader {
            override fun readServerUrl() = "https://test.invalid"
            override fun readAccessToken() = "test"
        })
        val old = TimelineMessage(id = "old", author = MessageAuthor.Agent, text = "old", orderSeq = 10, updatedSeq = 900)
        val state = SessionDetailState(timeline = SessionTimelineState(messages = listOf(old), nextSeq = 1000))
        val sent = controller.addOptimisticMessage("session", state, "question", "local-user")
        assertEquals(10, sent.messages.last().orderSeq)
        assertEquals(901, sent.messages.last().updatedSeq)
        val reply = TimelineMessage(id = "aaa-reply", author = MessageAuthor.Agent, text = "reply", orderSeq = 10, updatedSeq = 901)
        val duringStream = mergeOptimisticTimelineMessages(
            realMessages = listOf(old, reply), currentMessages = sent.messages,
            storedMessages = controller.optimisticMessages("session"), orderingItems = emptyList(),
        )
        assertEquals(listOf("old", "local-user", "aaa-reply"), duringStream.messages.map { it.id })
        val echo = TimelineMessage(id = "server-user", author = MessageAuthor.User, text = "question", orderSeq = 10, updatedSeq = 902, clientMessageId = "local-user")
        val acknowledged = mergeOptimisticTimelineMessages(
            realMessages = listOf(old, echo, reply.copy(updatedSeq = 903)), currentMessages = duringStream.messages,
            storedMessages = controller.optimisticMessages("session"), orderingItems = emptyList(),
        )
        assertEquals(listOf("old", "server-user", "aaa-reply"), acknowledged.messages.map { it.id })
        assertEquals(0, acknowledged.pending.size)
        val twice = controller.addOptimisticMessage("session", sent, "second", "aaa-second")
        assertEquals(listOf("old", "local-user", "aaa-second"), twice.messages.map { it.id })
    }

    @Test fun firstUserMessageStaysBeforeFirstReply() {
        val controller = SessionDetailController(SessionsApi(), object : AuthSessionReader {
            override fun readServerUrl() = "https://test.invalid"
            override fun readAccessToken() = "test"
        })
        val sent = controller.addOptimisticMessage("empty", SessionDetailState(), "question", "local-user")
        val reply = TimelineMessage(id = "aaa-reply", author = MessageAuthor.Agent, text = "reply", orderSeq = 1, updatedSeq = 1)
        val merged = mergeOptimisticTimelineMessages(
            realMessages = listOf(reply), currentMessages = sent.messages,
            storedMessages = controller.optimisticMessages("empty"), orderingItems = emptyList(),
        )
        assertEquals(listOf("local-user", "aaa-reply"), merged.messages.map { it.id })
    }

}
