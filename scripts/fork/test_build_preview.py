import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tarfile
import tempfile
import unittest

MODULE = runpy.run_path(str(Path(__file__).with_name('build-preview.py')))


class PreviewBuildTests(unittest.TestCase):
    def test_committed_payload_includes_upgrade_helper_and_verified_web(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            root.mkdir()
            files = {'connector/pyproject.toml': '[project]\nversion="2.6.4"\n',
                     'server/pyproject.toml': '[project]\nversion="2.6.4"\n',
                     'scripts/fork/update-preview.py': '# deploy',
                     'scripts/fork/upgrade-legacy-connector.py': '# upgrade',
                     'scripts/fork/runtime-broker.py': '# broker',
                     'connector/connector/runtimes/claude/history/deletion.py': '# scoped helper',
                     'connector/connector/runtimes/claude/usage_probe.py': '# local usage helper'}
            for name, value in files.items():
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
            for args in [['init', '-q'], ['add', '.'], ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture']]:
                subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
            web = root / 'web-next/out'
            web.mkdir(parents=True); (web / 'index.html').write_text('exported')
            (root / '.git/info/exclude').write_text('web-next/out/\n')
            function = MODULE['build']
            previous = function.__globals__['ROOT']
            function.__globals__['ROOT'] = root
            try:
                output = Path(directory) / 'preview.tar.gz'
                function(output)
                with tarfile.open(output) as archive:
                    manifest = json.load(archive.extractfile('manifest.json'))
                    self.assertEqual(manifest['version'], '2.6.4')
                    self.assertIn('upgrade-legacy-connector.py', manifest['files'])
                    self.assertIn('runtime-broker.py', manifest['files'])
                    self.assertIn('native-history-cleanup.py', manifest['files'])
                    self.assertIn('web-static/index.html', manifest['files'])
                    for name, digest in manifest['files'].items():
                        self.assertEqual(digest, hashlib.sha256(archive.extractfile(name).read()).hexdigest())
                with self.assertRaises(FileExistsError):
                    function(output)
                (root / 'connector/pyproject.toml').write_text('changed')
                with self.assertRaises(RuntimeError):
                    function(Path(directory) / 'dirty.tar.gz')
            finally:
                function.__globals__['ROOT'] = previous
