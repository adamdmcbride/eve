import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import eve_runtime_bundle as bundle


class RuntimeBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.runtime = Path(self.temp.name) / 'runtime'
        self.source.mkdir()
        self.runtime.mkdir()
        self.write('eve.py', 'import eve_feature\n')
        self.write('eve_feature.py', 'VALUE = 42\n')

    def write(self, name, contents):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def prepare(self, **kwargs):
        return bundle.prepare(self.source, [(str(p.relative_to(self.source)), p,
            self.runtime / p.relative_to(self.source)) for p in self.source.rglob('*.py')], **kwargs)

    def test_module_inventory_uses_platform_path_parts(self):
        from pathlib import PureWindowsPath
        with patch.object(bundle, 'Path', PureWindowsPath):
            self.assertEqual({'eve_commands', 'eve_commands.parser'},
                bundle._modules([r'eve_commands\__init__.py', r'eve_commands\parser.py']))

    def test_installs_complete_code_without_mutable_data(self):
        (self.runtime / '.eve').mkdir()
        db = self.runtime / '.eve' / 'memory.db'
        db.write_bytes(b'durable memory')
        with self.prepare() as candidate:
            result = bundle.install(self.runtime, candidate)
        self.assertTrue(result['verified'])
        self.assertEqual('passed', result['canary'])
        self.assertEqual('installed_not_activated', result['state'])
        self.assertEqual(b'durable memory', db.read_bytes())
        self.assertEqual('VALUE = 42\n', (self.runtime / 'eve_feature.py').read_text())
        (self.runtime / 'eve_feature.py').write_text('changed')
        self.assertFalse(bundle.verify(self.runtime)['verified'])

    def test_missing_module_not_masked_by_runtime_or_source_environment(self):
        (self.source / 'eve_feature.py').unlink()
        (self.runtime / 'eve_feature.py').write_text('VALUE = 42\n')
        with self.assertRaisesRegex(ValueError, 'Missing first-party'):
            with self.prepare(): pass
        self.assertFalse((self.runtime / 'eve.py').exists())

    def test_missing_package_initializer_rejected(self):
        self.write('eve_extra/leaf.py', 'VALUE = 1\n')
        with self.assertRaisesRegex(ValueError, 'initializer'):
            with self.prepare(): pass

    def test_syntax_error_rejected_before_install(self):
        self.write('eve_feature.py', 'broken python !')
        with self.assertRaises(SyntaxError):
            with self.prepare(): pass

    def test_source_changes_after_canary_rejected(self):
        with self.prepare() as candidate:
            self.write('eve_feature.py', 'VALUE = 0\n')
            with self.assertRaisesRegex(RuntimeError, 'Source changed'):
                bundle.install(self.runtime, candidate)
        self.assertFalse((self.runtime / bundle.MARKER).exists())

    def test_failed_install_rolls_back_and_removes_new_modules(self):
        (self.runtime / 'eve.py').write_text('old = 1\n')
        original = bundle._put
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path == self.runtime / 'eve_feature.py' and not failed:
                failed = True
                raise OSError('injected disk failure')
            return original(path, data)
        with self.prepare() as candidate, patch.object(bundle, '_put', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'injected'):
                bundle.install(self.runtime, candidate)
        self.assertEqual('old = 1\n', (self.runtime / 'eve.py').read_text())
        self.assertFalse((self.runtime / 'eve_feature.py').exists())
        self.assertFalse((self.runtime / bundle.MARKER).exists())

    def test_interrupted_transaction_is_recoverable(self):
        (self.runtime / 'eve.py').write_text('old = 1\n')
        original = bundle._put
        def crash(path, data):
            if path == self.runtime / 'eve_feature.py': raise KeyboardInterrupt()
            return original(path, data)
        with self.prepare() as candidate, patch.object(bundle, '_put', side_effect=crash), patch.object(bundle, '_recover_unlocked'):
            with self.assertRaises(KeyboardInterrupt): bundle.install(self.runtime, candidate)
        with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
            bundle.verify(self.runtime)
        self.assertEqual('rolled_back', bundle.recover(self.runtime)['state'])
        self.assertEqual('old = 1\n', (self.runtime / 'eve.py').read_text())

    def test_rollback_will_not_overwrite_a_foreign_edit(self):
        original = bundle._put
        def race(path, data):
            if path == self.runtime / 'eve_feature.py':
                (self.runtime / 'eve.py').write_text('foreign edit')
                raise OSError('failed')
            return original(path, data)
        with self.prepare() as candidate, patch.object(bundle, '_put', side_effect=race):
            with self.assertRaisesRegex(RuntimeError, 'Concurrent code change prevents'):
                bundle.install(self.runtime, candidate)
        self.assertEqual('foreign edit', (self.runtime / 'eve.py').read_text())
        self.assertTrue((self.runtime / bundle.MARKER).exists())

    def test_symlink_destination_rejected(self):
        elsewhere = Path(self.temp.name) / 'outside.py'
        elsewhere.write_text('outside')
        (self.runtime / 'eve_feature.py').symlink_to(elsewhere)
        with self.prepare() as candidate, self.assertRaises(ValueError):
            bundle.install(self.runtime, candidate)
        self.assertEqual('outside', elsewhere.read_text())

    def test_import_canary_is_hermetic_from_user_home(self):
        self.write('eve_feature.py', 'import os\nassert "API_KEY" not in os.environ\nassert os.environ["USERPROFILE"] == os.environ["HOME"]\n')
        with patch.dict('os.environ', {'API_KEY': 'fixture-not-a-secret'}):
            with self.prepare() as candidate:
                self.assertEqual('passed', candidate['manifest']['canary'])
