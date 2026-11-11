from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

module = runpy.run_path(str(Path(__file__).with_name('upgrade-legacy-connector.py')))


class SwitchTests(unittest.TestCase):
    def test_switch_keeps_original_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, backup = (root / n for n in ['old', 'new', 'backup'])
            old.mkdir(); new.mkdir()
            (old / 'original').write_text('saved')
            calls = []
            with patch('time.sleep'):
                module['switch'](old, new, backup, calls.append)
            self.assertEqual(old.resolve(), new)
            self.assertEqual((backup / 'original').read_text(), 'saved')
            self.assertEqual(calls[-1][1], 'is-active')

    def test_failed_health_restores_original_path_and_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, backup = (root / n for n in ['old', 'new', 'backup'])
            old.mkdir(); new.mkdir()
            (old / 'original').write_text('saved')
            calls = []
            def command(args):
                calls.append(args)
                if args[1] == 'is-active':
                    raise RuntimeError('new service failed')
            with patch('time.sleep'), self.assertRaises(RuntimeError):
                module['switch'](old, new, backup, command)
            self.assertFalse(old.is_symlink())
            self.assertEqual((old / 'original').read_text(), 'saved')
            self.assertEqual(calls[-1][1], 'start')
            self.assertFalse(backup.exists())
