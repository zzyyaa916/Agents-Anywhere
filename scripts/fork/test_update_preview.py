import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

module = runpy.run_path(str(Path(__file__).with_name('update-preview.py')))


class UpdatePreviewTests(unittest.TestCase):
    def test_payload_accepts_only_matching_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sample').write_text('ok')
            (root / 'manifest.json').write_text(json.dumps({'version': module['VERSION'], 'files': {'sample': hashlib.sha256(b'ok').hexdigest()}}))
            module['verify'](root)
            (root / 'sample').write_text('changed')
            with self.assertRaises(RuntimeError):
                module['verify'](root)

    def test_payload_cannot_escape_update_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifest.json').write_text(json.dumps({'version': module['VERSION'], 'files': {'../outside': 'bad'}}))
            with self.assertRaises(RuntimeError):
                module['verify'](root)

    def test_endpoint_must_be_present_and_require_login(self):
        for status in [401, 404, 405]:
            with patch('urllib.request.urlopen', side_effect=HTTPError('http://test', status, 'test', {}, None)):
                if status == 401:
                    module['protected']('http://test')
                else:
                    with self.assertRaises(RuntimeError):
                        module['protected']('http://test')

    def test_migration_failure_never_restarts_an_incompatible_old_image(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = base / "fork.env"
            config.write_text("FORK_IMAGE=old-image\n")
            (base / "compose.yml").write_text("synthetic compose")
            revision = ["v2_57"]
            calls = []
            def command(args, **kwargs):
                calls.append(args)
                if "psql" in args:
                    return revision[0] if "alembic_version" in args[-1] else "0"
                if args[:3] == ["docker", "ps", "-q"]: return ""
                if args[:2] == ["docker", "inspect"]:
                    if "--format={{.Config.Image}}" in args: return "old-image"
                    if "--format={{.Image}}" in args: return "image-id"
                    return "[]"
                if args[:3] == ["docker", "image", "inspect"]: return "image-id"
                if "migration.log" == getattr(kwargs.get("log"), "name", None): revision[0] = "v2_58"
                return ""
            def process(args, **kwargs):
                if "pg_dump" in args: kwargs["stdout"].write(b"synthetic-backup")
                return SimpleNamespace(returncode=0)
            function = module["update_server"]
            def path(value): return base if value == "/opt/agents-anywhere-fork" else Path(value)
            with patch.dict(function.__globals__, {"Path": path, "run": command,
                "get": lambda _: {"status": "ok", "version": "2.6.2"}, "protected": lambda _: None}), patch("subprocess.run", side_effect=process):
                with self.assertRaisesRegex(RuntimeError, "旧镜像可能拒绝新 schema"):
                    function(base, {"source": "a" * 40, "files": {}})
            self.assertIn(module["VERSION"], config.read_text())
            self.assertEqual(sum("up" in args and "server" in args for args in calls), 1)


if __name__ == '__main__':
    unittest.main()
