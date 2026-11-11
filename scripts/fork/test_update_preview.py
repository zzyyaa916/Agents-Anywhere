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
            (root / 'manifest.json').write_text(json.dumps({'files': {'sample': hashlib.sha256(b'ok').hexdigest()}}))
            module['verify'](root)
            (root / 'sample').write_text('changed')
            with self.assertRaises(RuntimeError):
                module['verify'](root)

    def test_payload_cannot_escape_update_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifest.json').write_text(json.dumps({'files': {'../outside': 'bad'}}))
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


if __name__ == '__main__':
    unittest.main()
