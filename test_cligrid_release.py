"""Release guards: the things that make a download dead on arrival.

Every module the application imports has to reach every artifact, and the
version has to read the same everywhere. Both broke once by hand-editing
lists, so these tests pin the single sources of truth: pyproject.toml for the
module list and the version, and a glob (never a hand-written list) in the
scripts that copy modules.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def pyproject_version():
    return re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT, re.M).group(1)


def pyproject_modules():
    block = re.search(r"py-modules\s*=\s*\[(.*?)\]", PYPROJECT, re.S).group(1)
    return sorted(re.findall(r'"([^"]+)"', block))


def source_modules():
    return sorted(path.stem for path in ROOT.glob("cligrid*.py"))


def imported_modules():
    """Every cligrid_* module some application module imports."""
    names = set()
    for path in ROOT.glob("cligrid*.py"):
        for match in re.finditer(r"^\s*import\s+(cligrid_\w+)|^\s*from\s+(cligrid_\w+)\s+import",
                                 path.read_text(encoding="utf-8"), re.M):
            names.add(match.group(1) or match.group(2))
    return sorted(names)


class ModuleListTests(unittest.TestCase):
    def test_pyproject_lists_every_source_module(self):
        self.assertEqual(pyproject_modules(), source_modules())

    def test_every_imported_module_is_a_source_module(self):
        missing = set(imported_modules()) - set(source_modules())
        self.assertEqual(missing, set())

    def test_packagers_copy_modules_by_glob_not_by_hand(self):
        # A literal list of module names in a packager is how cligrid_palette
        # went missing from every artifact. The scripts glob cligrid*.py.
        scripts = [
            ROOT / "install.sh",
            ROOT / "packaging/linux/build-tarball.sh",
            ROOT / "packaging/build-deb.sh",
            ROOT / "packaging/macos/install-macos.sh",
            ROOT / "packaging/windows/wsl-provision.sh",
        ]
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                self.assertIn("cligrid*.py", text)
                self.assertNotRegex(text, r"cligrid_art\s+cligrid_state",
                                    "hand-written module list")


class VersionTests(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(pyproject_version(), r"^\d+\.\d+\.\d+$")

    def test_application_reports_the_pyproject_version(self):
        text = (ROOT / "cligrid.py").read_text(encoding="utf-8")
        version = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M).group(1)
        self.assertEqual(version, pyproject_version())

    def test_scripts_read_the_version_instead_of_hardcoding_it(self):
        reader = (ROOT / "packaging/version.py").read_text(encoding="utf-8")
        self.assertIn("pyproject.toml", reader)
        for name in ("packaging/build-deb.sh", "packaging/macos/install-macos.sh",
                     "packaging/macos/build-dmg.sh", "packaging/windows/build-exe.sh",
                     "packaging/verify-platforms.sh", "packaging/linux/build-tarball.sh"):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertNotIn("4.0.0", text)
                self.assertIn("version.py", text)

    def test_workflows_do_not_hardcode_the_version(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            with self.subTest(workflow=path.name):
                self.assertNotIn("4.0.0", path.read_text(encoding="utf-8"))

    def test_changelog_has_a_section_for_this_version(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(changelog, re.compile(r"^## %s\b" % re.escape(pyproject_version()), re.M))

    def test_pipx_metadata_points_at_the_homepage(self):
        self.assertIn("readme = \"README.md\"", PYPROJECT)
        self.assertIn("kuttystauder.com/development", PYPROJECT)
        self.assertIn("cligrid = \"cligrid:main_entry\"", PYPROJECT)

    def test_aur_pkgbuild_version_matches_pyproject(self):
        text = (ROOT / "packaging/aur/PKGBUILD").read_text(encoding="utf-8")
        match = re.search(r"^pkgver=(.+)$", text, re.M)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), pyproject_version())
        self.assertIn("cligrid*.py", text)
        self.assertIn("python-gobject", text)


class DocumentationCoverageTests(unittest.TestCase):
    """Every verb the socket accepts is in `cligrid --help`, answers
    `cligrid help <verb>`, and has a man page entry. control.VERBS is the
    single list; the documents are held to it here instead of by hand."""

    def test_help_table_covers_every_verb(self):
        import cligrid_art
        import cligrid_control
        missing = set(cligrid_control.VERBS) - cligrid_art.documented_verbs()
        self.assertEqual(missing, set(), "verbs missing from HELP_SECTIONS")

    def test_man_page_covers_every_verb(self):
        import cligrid_control
        text = (ROOT / "cligrid.1").read_text(encoding="utf-8")
        entries = " ".join(re.findall(r"^\.B (.+)$", text, re.M))
        missing = [verb for verb in cligrid_control.VERBS
                   if not re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(verb), entries)]
        self.assertEqual(missing, [], "verbs missing from the man page")
        self.assertNotRegex(text, r"^\.TH .*\d+\.\d+\.\d+", "man page header hardcodes a version")

    def test_every_alias_folds_onto_a_documented_verb(self):
        import cligrid_art
        import cligrid_control
        for alias, verb in cligrid_art.VERB_ALIASES.items():
            self.assertIn(alias, cligrid_control.VERBS)
            self.assertIn(verb, cligrid_control.VERBS)
            self.assertEqual(cligrid_art.canonical_verb(alias), verb)


class DownloadLayoutTests(unittest.TestCase):
    def test_license_is_freeware_not_open_source(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("All rights reserved", text)
        self.assertIn("Kutty Stauder", text)
        self.assertIn("free of charge", text)
        self.assertIn("kuttystauder.com/development", text)
        self.assertNotIn("MIT License", text)
        self.assertNotIn("Permission is hereby granted, free of charge, to any person", text)

    def test_linux_installer_copies_the_app_out_of_the_extract(self):
        # A download that leaves the launcher pointing at the unzipped folder
        # dies the moment that folder is deleted. The installer copies the
        # modules into an app dir and aims the launcher there.
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("cligrid*.py", text)
        self.assertIn("share/cligrid", text)
        self.assertIn("app_dir", text)

    def test_archive_includes_what_the_installers_read(self):
        text = (ROOT / "packaging/linux/build-tarball.sh").read_text(encoding="utf-8")
        for name in ("pyproject.toml", "LICENSE", "CHANGELOG.md", "version.py", "PKGBUILD"):
            self.assertIn(name, text)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_workflow_publishes_archives_deb_and_checksums(self):
        # verify-platforms.sh builds the tarball, zip and deb and checks them;
        # the workflow then signs off with checksums and a GitHub Release.
        text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        for needle in ("tags:", "verify-platforms.sh", "SHA256SUMS", "gh release create",
                       ".tar.gz", ".zip", "_all.deb", ".exe", ".dmg", "pyproject.toml"):
            self.assertIn(needle, text)

    def test_windows_nsi_takes_version_from_the_builder(self):
        text = (ROOT / "packaging/windows/cligrid.nsi").read_text(encoding="utf-8")
        self.assertIn("!ifndef VERSION", text)
        self.assertIn("install-windows.ps1", text)
        self.assertNotIn("4.0.0", text)


if __name__ == "__main__":
    unittest.main()
