"""Exercise the real archive builder without touching release artifacts."""

import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest


class ArchivePrivacyTests(unittest.TestCase):
    def test_portable_archive_does_not_publish_builder_account(self):
        source = pathlib.Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            checkout = pathlib.Path(temporary) / "source"
            shutil.copytree(source, checkout, ignore=shutil.ignore_patterns(
                ".git", ".troika", "__pycache__", ".cache", "dist", "docs"))
            subprocess.run(["bash", "packaging/linux/build-tarball.sh"],
                           cwd=checkout, check=True, capture_output=True)
            archives = list((checkout / "packaging/dist").glob("*.tar.gz"))
            self.assertEqual(len(archives), 1)
            with tarfile.open(archives[0]) as archive:
                members = archive.getmembers()
                self.assertTrue(members)
                for member in members:
                    with self.subTest(member=member.name):
                        self.assertEqual((member.uid, member.gid), (0, 0))
                        self.assertIn(member.uname, ("", "root"))
                        self.assertIn(member.gname, ("", "root"))
                        self.assertFalse(member.pax_headers)


if __name__ == "__main__":
    unittest.main()
