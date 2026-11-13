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
    @Test fun closeClearsOnlyThisAccountsView() {
        val context = RuntimeEnvironment.getApplication() as Context
        val first = JointConversationStore(context, "close:one")
        val other = JointConversationStore(context, "close:two")
        val state = JointConversationState("project", listOf("one", "two"), "draft", setOf("one"))
        first.save(state); other.save(state)
        first.clear()
        assertEquals(JointConversationState(), first.read())
        assertEquals(state, other.read())
    }
    @Test fun legacyRecoverySelectionIsDiscardedWithoutTouchingOtherScopes() {
        val context = RuntimeEnvironment.getApplication() as Context
        val preferences = context.getSharedPreferences("fork-joint-conversations", Context.MODE_PRIVATE)
        val state = JointConversationState("old-project", listOf("deleted-one", "deleted-two"))
        preferences.edit().putString("v1:legacy", encodeJointState(state)).putString("v1:other", encodeJointState(state)).commit()
        assertEquals(JointConversationState(), JointConversationStore(context, "legacy").read())
        assertEquals(false, preferences.contains("v1:legacy"))
        assertEquals(true, preferences.contains("v1:other"))
    }
}
