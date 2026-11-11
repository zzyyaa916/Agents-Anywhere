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

    def test_symlink_upgrade_and_failed_start_restore_same_target(self):
        for failed in [False, True]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original, new, link, backup = (root / n for n in ['original', 'new', 'venv', 'backup'])
                original.mkdir(); new.mkdir(); link.symlink_to(original)
                calls = []
                def command(args):
                    calls.append(args)
                    if failed and args[1] == 'is-active':
                        raise RuntimeError('failed health')
                with patch('time.sleep'):
                    if failed:
                        with self.assertRaises(RuntimeError):
                            module['switch'](link, new, backup, command)
                    else:
                        module['switch'](link, new, backup, command)
                self.assertEqual(link.resolve(), original if failed else new)
                self.assertTrue(original.is_dir())

    def test_post_start_validation_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, backup = (root / n for n in ['old', 'new', 'backup'])
            old.mkdir(); new.mkdir()
            def failed():
                raise RuntimeError('pairing/profile validation failed')
            with patch('time.sleep'), self.assertRaises(RuntimeError):
                module['switch'](old, new, backup, lambda args: None, validate=failed)
            self.assertTrue(old.is_dir())
            self.assertFalse(old.is_symlink())


class InstallPackageTests(unittest.TestCase):
    def test_verified_wheel_is_installed_without_network_or_build_dependencies(self):
        calls = []
        module['install_package'](Path('/bundle'), {'files': {'anywhere_cli-2.6.2-py3-none-any.whl': 'verified'}}, '/uv', Path('/new/bin/python'), lambda args, **kw: calls.append((args, kw)))
        self.assertIn('--no-index', calls[0][0])
        self.assertEqual('/bundle/anywhere_cli-2.6.2-py3-none-any.whl', calls[0][0][-1])
        self.assertTrue(calls[0][1]['check'])

    def test_unlisted_wheel_is_not_trusted(self):
        calls = []
        module['install_package'](Path('/bundle'), {'files': {}}, '/uv', Path('/new/bin/python'), lambda args, **kw: calls.append(args))
        self.assertNotIn('--no-index', calls[0])
        self.assertEqual('/bundle/connector', calls[0][-1])
