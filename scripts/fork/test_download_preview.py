import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('download-preview.sh')


class DownloadTests(unittest.TestCase):
    def test_hash_verified_before_publishing_and_completed_download_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curl = root / 'curl'
            curl.write_text('#!/bin/bash\nwhile [[ $1 != --output ]]; do shift; done\nprintf payload > "$2"\n')
            curl.chmod(0o700)
            target = root / 'archive.tar.gz'
            environment = {**os.environ, 'PATH': str(root) + ':' + os.environ['PATH']}
            command = ['bash', str(SCRIPT), '2.6.2', '0' * 64, str(target)]
            failed = subprocess.run(command, env=environment, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(target.exists())
            self.assertFalse(Path(str(target) + ".part").exists(), "corrupt complete file must not poison the next resume")
            command[3] = hashlib.sha256(b'payload').hexdigest()
            subprocess.run(command, env=environment, capture_output=True, check=True)
            self.assertEqual(target.read_bytes(), b'payload')
            curl.write_text('#!/bin/bash\nexit 99\n')
            subprocess.run(command, env=environment, capture_output=True, check=True)
