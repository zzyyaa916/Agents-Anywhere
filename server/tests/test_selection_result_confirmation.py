import unittest
from types import SimpleNamespace

from agent_server.core.runtime_identity import SessionRuntimeBindingError
from agent_server.services.session_run import _runtime_state_from_selection_result


class SelectionResultConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.session = SimpleNamespace(id='s', runtime='claude', runtimeId='rti_one', externalSessionId='n', updatedSeq=1)
        self.requested = {'model': 'requested/low'}

    def project(self, result):
        return _runtime_state_from_selection_result(self.session, self.requested, result)

    def test_missing_runtime_receipt_never_echoes_request(self):
        for result in ({}, {'state': {}}, None):
            with self.subTest(result=result):
                state = self.project(result)
                self.assertEqual(state.selections, {})
                self.assertNotIn('selection_effect', state.metadata)

    def test_only_explicit_runtime_values_and_effect_are_returned(self):
        state = self.project({'selections': {'model': 'canonical/low'}, 'selectionEffect': 'next_turn'})
        self.assertEqual(state.selections, {'model': 'canonical/low'})
        self.assertEqual(state.metadata['selection_effect'], 'next_turn')

    def test_applied_flag_is_authoritative(self):
        for applied, effect in [(True, 'applied'), (False, 'next_turn')]:
            with self.subTest(applied=applied):
                state = self.project({'applied': applied, 'state': {'selections': {'model': 'canonical/low'}, 'metadata': {'selection_effect': 'applied'}}})
                self.assertEqual(state.metadata['selection_effect'], effect)

    def test_other_session_cannot_confirm_this_session(self):
        with self.assertRaises(SessionRuntimeBindingError):
            self.project({'state': {'sessionId': 'other', 'selections': self.requested}})
