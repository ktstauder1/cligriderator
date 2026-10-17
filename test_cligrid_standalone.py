"""Frozen macOS behavior, checked without needing a Mac to run unit tests."""

import importlib.util
import io
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import cligrid_doctor as doctor

ROOT = Path(__file__).resolve().parent


class StandaloneDoctorTests(unittest.TestCase):
    def test_frozen_diagnostics_need_no_homebrew_or_external_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            contents = Path(tmp) / 'Moved App.app/Contents'
            executable = contents / 'MacOS/cligrid'
            executable.parent.mkdir(parents=True)
            executable.touch()
            (contents / 'Info.plist').touch()
            resources = contents / 'Frameworks'
            (resources / 'bin').mkdir(parents=True)
            (resources / 'bin/tmux').touch()
            commands = []

            def run(argv):
                commands.append(argv)
                return True, 'exact' if doctor.PANGO_FAMILIES in argv else 'ok'

            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, '_MEIPASS', str(resources), create=True), \
                    patch.object(sys, 'executable', str(executable)), \
                    patch.object(sys, 'platform', 'darwin'), \
                    patch.object(doctor, '_run', side_effect=run):
                rows = doctor.checks(Path(tmp) / 'missing-config.json')
            self.assertEqual(len(rows), 10)
            self.assertTrue(all(row['ok'] for row in rows), rows)
            self.assertNotIn('homebrew', {row['name'] for row in rows})
            self.assertFalse(any('brew' in arg for cmd in commands for arg in cmd))


class FrozenEntryTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            'standalone_entry', ROOT / 'packaging/macos/standalone_entry.py')
        self.entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.entry)

    def test_banner_subprocess_uses_embedded_module(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = self.entry.helper(['cligrid', '/moved bundle/cligrid_art.py',
                                      'banner', '--pane', '3', '--name', 'test-pane'])
        self.assertEqual(code, 0)
        self.assertIn('test-pane', output.getvalue())

    def test_unknown_python_code_is_rejected(self):
        with self.assertRaises(ValueError):
            self.entry.helper(['cligrid', '-c', 'raise AssertionError("must not run")'])

    def test_normal_commands_are_left_for_the_application(self):
        self.assertIsNone(self.entry.helper(['cligrid', 'version']))

    def test_macos_caps_descriptor_limit_without_lowering_hard_limit(self):
        with patch.object(sys, 'platform', 'darwin'), \
                patch.object(resource, 'getrlimit', return_value=(1048575, resource.RLIM_INFINITY)), \
                patch.object(resource, 'setrlimit') as set_limit:
            self.entry.configure_macos_runtime()
        set_limit.assert_called_once_with(resource.RLIMIT_NOFILE, (65536, resource.RLIM_INFINITY))

    def test_macos_preserves_existing_lower_descriptor_limit(self):
        with patch.object(sys, 'platform', 'darwin'), \
                patch.object(resource, 'getrlimit', return_value=(1024, 4096)), \
                patch.object(resource, 'setrlimit') as set_limit:
            self.entry.configure_macos_runtime()
        set_limit.assert_not_called()

    def test_other_platforms_do_not_change_descriptor_limit(self):
        with patch.object(sys, 'platform', 'linux'), patch.object(resource, 'setrlimit') as set_limit:
            self.entry.configure_macos_runtime()
        set_limit.assert_not_called()

    def test_entry_can_run_a_real_banner_without_importing_the_gui(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), NO_COLOR='1')
        result = subprocess.run(
            [sys.executable, str(ROOT / 'packaging/macos/standalone_entry.py'),
             '/moved/cligrid_art.py', 'banner', '--name', 'child-pane'],
            env=env, capture_output=True, text=True, check=True,
        )
        self.assertIn('child-pane', result.stdout)


class BundleAuditTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            'bundle_tools', ROOT / 'packaging/macos/bundle_tools.py')
        self.tools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tools)

    def test_homebrew_library_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'External library'):
            self.tools.validate_load_paths(
                ['/opt/homebrew/opt/glib/lib/libglib.dylib'], [])

    def test_homebrew_rpath_is_rejected_even_without_absolute_dependencies(self):
        with self.assertRaisesRegex(ValueError, 'External rpath'):
            self.tools.validate_load_paths(['@rpath/libglib.dylib'], ['/usr/local/lib'])

    def test_system_libraries_and_relative_bundle_paths_are_allowed(self):
        self.tools.validate_load_paths(
            ['/usr/lib/libSystem.B.dylib', '/System/Library/Frameworks/AppKit.framework/AppKit',
             '@rpath/libglib.dylib', '@loader_path/../libncurses.dylib'],
            ['@loader_path/..', '@executable_path/../Frameworks'])

    def test_unresolved_relative_library_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'External library'):
            self.tools.validate_load_paths(['libglib.dylib'], [])


if __name__ == '__main__':
    unittest.main()
