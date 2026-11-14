import unittest

from agent_server.core.history_deletion import cleanup_failure_message


class CleanupFailureMessageTest(unittest.TestCase):
    def test_known_failure_reasons_are_actionable(self):
        for reason, expected in [
            ("native_history_deletion_unsupported", "尚不支持"),
            ("cleanup_shared_project_path", "重叠"),
            ("protected_cleanup_path", "受保护"),
            ("cleanup_permission_denied", "权限"),
        ]:
            with self.subTest(reason=reason):
                self.assertIn(expected, cleanup_failure_message(ValueError(reason), "fallback"))

    def test_unknown_error_never_exposes_paths_or_upstream_details(self):
        self.assertEqual(cleanup_failure_message(RuntimeError("sensitive-path-and-details"), "fallback"), "fallback")
