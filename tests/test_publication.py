import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import package
from scripts.audit_public import inspect_entries
from scripts.publication import source_files


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('package.json', 'package-lock.json', 'plugin.json', 'main.py', 'README.md',
                     'README.zh-CN.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'SECURITY.md',
                     'CONTRIBUTING.md', 'CHANGELOG.md', 'tsconfig.json', 'rollup.config.js',
                     'dist/index.js', 'src/index.tsx', 'scripts/install-on-deck.sh', 'docs/AUTH.md'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'version': '0.1.9'}) if name == 'package.json' else 'public fixture')
        for name in ('docs/DEPLOYMENT-device.md', 'docs/FIXES-local.md', 'docs/REVIEW-local.md',
                     'docs/auth.json', 'resources/settings.json', 'licenses/.DS_Store'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('private fixture must never be published')

    def test_install_archive_excludes_private_notes_and_runtime_files(self):
        with patch.object(package, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()):
            package.package(lite=True)
        with zipfile.ZipFile(self.root / 'out/decky-agent-0.1.9-lite.zip') as archive:
            self.assertIn('Decky Agent/docs/AUTH.md', archive.namelist())
            self.assertNotIn('private fixture must never be published', b''.join(archive.read(n) for n in archive.namelist()).decode())
            self.assertIn('Decky Agent/README.zh-CN.md', archive.namelist())

    def test_symlink_cannot_pull_an_external_file_into_the_release(self):
        secret = self.root / 'outside.txt'
        secret.write_text('private fixture must never be published')
        (self.root / 'resources/codex-models.json').symlink_to(secret)
        with patch.object(package, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            package.package(lite=True)

    def test_frontend_source_symlink_is_rejected_before_packaging(self):
        secret = self.root / 'outside.txt'
        secret.write_text('private fixture must never be published')
        (self.root / 'src/linked.ts').symlink_to(secret)
        with patch.object(package, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            package.package(lite=True)

    def test_public_source_manifest_excludes_local_notes_and_runtime(self):
        for name in ('src/.private/local.ts', 'tests/__pycache__/local.py', '.env', 'auth.json', 'out/old.zip'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('private fixture must never be published')
        files = source_files(self.root)
        self.assertFalse(any('private fixture' in path.read_text() for path in files))
        self.assertIn(self.root / 'src/index.tsx', files)

    def test_privacy_scan_rejects_credentials_homes_and_runtime_data_without_echoing_them(self):
        key = 'sk-' + 'testsecretvalue123456789012345'
        home = '/Users/' + 'developer/project'
        entries = [('src/config.ts', (key + '\n' + home).encode()), ('sessions/one.json', b'{}')]
        issues = inspect_entries(entries)
        self.assertEqual({item['rule'] for item in issues}, {'credential', 'developer-home', 'private-file'})
        self.assertNotIn(key, json.dumps(issues))
        self.assertNotIn(home, json.dumps(issues))

    def test_privacy_scan_accepts_documentation_addresses_and_fixture_emails(self):
        self.assertEqual(inspect_entries([('tests/example.py', b'http://127.0.0.1:1337 https://192.0.2.1 test@example.com')]), [])

    def test_privacy_scan_rejects_personal_emails_and_private_network_addresses(self):
        email = 'person@' + 'private.invalid'
        address = '192.168.' + '44.55'
        issues = inspect_entries([('README.md', (email + '\n' + address).encode())])
        self.assertEqual({item['rule'] for item in issues}, {'email', 'network-address'})

    def test_registry_warning_exception_does_not_hide_root_author_email(self):
        email = 'maintainer@' + 'upstream.invalid'
        lock = {'packages': {'node_modules/example': {'deprecated': 'Public warning: ' + email},
                             '': {'author': email}}}
        issues = inspect_entries([('package-lock.json', json.dumps(lock, indent=2).encode())])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['rule'], 'email')
