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
        module['install_package'](Path('/bundle'), {'files': {'anywhere_cli-2.6.5-py3-none-any.whl': 'verified'}}, '/uv', Path('/new/bin/python'), lambda args, **kw: calls.append((args, kw)))
        self.assertIn('--no-index', calls[0][0])
        self.assertEqual('/bundle/anywhere_cli-2.6.5-py3-none-any.whl', calls[0][0][-1])
        self.assertTrue(calls[0][1]['check'])

    def test_unlisted_wheel_is_not_trusted(self):
        calls = []
        module['install_package'](Path('/bundle'), {'files': {}}, '/uv', Path('/new/bin/python'), lambda args, **kw: calls.append(args))
        self.assertNotIn('--no-index', calls[0])
        self.assertEqual('/bundle/connector', calls[0][-1])


class PrepareEnvironmentTests(unittest.TestCase):
    def test_failed_copy_install_or_check_removes_only_new_environment(self):
        for phase in ["copy", "install", "check", "import"]:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                old, new = root / "old", root / "new"
                old.mkdir(); new.mkdir()
                (old / "auth.json").write_text("synthetic-native-login")
                def command(args, **kwargs):
                    if args[0] == "cp":
                        (new / "partial").write_text("partially copied environment")
                        if phase == "copy": raise RuntimeError(phase)
                    if "check" in args and phase == "check": raise RuntimeError(phase)
                def install(*args):
                    if phase == "install": raise RuntimeError(phase)
                def run(args):
                    if phase == "import": raise RuntimeError(phase)
                    return "OK"
                globals_ = module["prepare_environment"].__globals__
                with patch.dict(globals_, {"install_package": install, "run": run}), patch.object(globals_["subprocess"], "run", command):
                    with self.assertRaisesRegex(RuntimeError, phase):
                        module["prepare_environment"](root, {"files": {}}, "uv", old, new)
                self.assertFalse(new.exists())
                self.assertEqual((old / "auth.json").read_text(), "synthetic-native-login")


class NativeCleanupUpgradeTests(unittest.TestCase):
    def test_identical_root_owned_helpers_do_not_restart_runtime(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = root / "bundle"; installed = root / "installed"
            bundle.mkdir(); installed.mkdir()
            broker, helper = installed / "broker", installed / "native-history-cleanup.py"
            probe = installed / "claude-usage-probe.py"
            for source, target in [("runtime-broker.py", broker), ("native-history-cleanup.py", helper), ("claude-usage-probe.py", probe)]:
                (bundle / source).write_bytes(b"unchanged helper")
                target.write_bytes(b"unchanged helper")
            calls = []
            def command(args):
                calls.append(args)
                return str(broker) if args[1] == "show" else ""
            actual_stat = Path.stat
            def root_owned(path, *args, **kwargs):
                result = actual_stat(path, *args, **kwargs)
                if path in (broker, helper, probe):
                    values = list(result); values[4] = 0
                    return os.stat_result(values)
                return result
            manifest = {"files": {name: "verified" for name in ("runtime-broker.py", "native-history-cleanup.py", "claude-usage-probe.py")}}
            with patch.object(Path, "stat", root_owned):
                module["install_native_cleanup"](bundle, manifest, "AA_FORK_RUNTIME_BROKER=1", command, broker=broker, helper=helper)
            self.assertFalse(any("restart" in args for args in calls))
            self.assertFalse((bundle / "runtime-broker.before.py").exists())

    def test_broker_install_and_restart_failure_restore_both_files(self):
        import os
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                broker, helper = root / "broker", root / "helper"
                broker.write_bytes(b"old broker"); helper.write_bytes(b"old helper")
                (root / "runtime-broker.py").write_bytes(b"new broker")
                (root / "native-history-cleanup.py").write_bytes(b"new helper")
                manifest = {"files": {"runtime-broker.py": "verified", "native-history-cleanup.py": "verified"}}
                calls = []
                def command(args):
                    calls.append(args)
                    if args[1] == "show": return str(broker)
                    if fail and args[1] == "is-active": raise RuntimeError("restart failed")
                    return ""
                actual_stat = Path.stat
                def root_owned(path, *args, **kwargs):
                    result = actual_stat(path, *args, **kwargs)
                    if path == broker:
                        values = list(result); values[4] = 0
                        return os.stat_result(values)
                    return result
                with patch.object(Path, "stat", root_owned), patch("os.chown"):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, "restart failed"):
                            module["install_native_cleanup"](root, manifest, "AA_FORK_RUNTIME_BROKER=1", command, broker=broker, helper=helper)
                    else:
                        module["install_native_cleanup"](root, manifest, "AA_FORK_RUNTIME_BROKER=1", command, broker=broker, helper=helper)
                self.assertEqual(broker.read_bytes(), b"old broker" if fail else b"new broker")
                self.assertEqual(helper.read_bytes(), b"old helper" if fail else b"new helper")
                self.assertEqual((root / "runtime-broker.before.py").read_bytes(), b"old broker")
