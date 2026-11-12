import json
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VersionTests(unittest.TestCase):
    def test_fork_release_versions_match(self):
        expected = tomllib.loads((ROOT / 'connector/pyproject.toml').read_text())['project']['version']
        self.assertEqual(expected, tomllib.loads((ROOT / 'server/pyproject.toml').read_text())['project']['version'])
        for name in ['desktop-workbench/package.json', 'desktop-workbench/renderer/package.json', 'web-next/package.json', 'dsh-bridge-next/package.json']:
            self.assertEqual(expected, json.loads((ROOT / name).read_text())['version'], name)
        for name, pattern in [('android/app/build.gradle.kts', r'versionName = "([^"]+)"'), ('server/agent_server/app.py', r'version="([^"]+)"'), ('scripts/fork/update-preview.py', r"VERSION = '([^']+)'"), ('scripts/fork/upgrade-legacy-connector.py', r"VERSION = '([^']+)'")]:
            self.assertEqual(expected, re.search(pattern, (ROOT / name).read_text())[1], name)

    def test_ios_release_configurations_match_connector(self):
        expected = tomllib.loads((ROOT / 'connector/pyproject.toml').read_text())['project']['version']
        project = (ROOT / 'ios/Agents Anywhere/Agents Anywhere.xcodeproj/project.pbxproj').read_text()
        self.assertEqual({expected}, set(re.findall(r'MARKETING_VERSION = ([^;]+);', project)))

    def test_fork_defaults_never_download_the_official_application(self):
        config = json.loads((ROOT / 'desktop-workbench/config.json').read_text())
        self.assertEqual('https://81.71.71.114:9443', config['cloud']['serverUrl'])
        self.assertEqual(config['cloud']['serverUrl'], config['cloud']['oauthWebOrigin'])
        for name in ['web-next/src/lib/product-links.ts', 'desktop-workbench/renderer/src/lib/product-links.ts']:
            text = (ROOT / name).read_text()
            self.assertNotIn('anywhere-labs/Agents-Anywhere', text)
            self.assertIn('zzyyaa916/Agents-Anywhere/releases', text)
