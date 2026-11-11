package com.agentsanywhere.app.feature.taskgroups

import android.content.Context
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class JointConversationStoreTest {
    @Test fun selectionIsIsolatedByServerAndUserAndSurvivesRecreation() {
        val context = RuntimeEnvironment.getApplication() as Context
        val first = JointConversationStore(context, "server-one:user-one")
        val state = JointConversationState("project", listOf("one", "two"), "draft", setOf("one"))
        first.save(state)
        assertEquals(state, JointConversationStore(context, "server-one:user-one").read())
        assertEquals(JointConversationState(), JointConversationStore(context, "server-one:user-two").read())
        assertEquals(JointConversationState(), JointConversationStore(context, "server-two:user-one").read())
    }
}
