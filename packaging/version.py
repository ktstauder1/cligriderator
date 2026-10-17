#!/usr/bin/env python3
"""Print the project version from pyproject.toml.

The packagers call this so the Debian control file, the macOS Info.plist,
the archive names and the verify script cannot drift from each other.
"""
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parent.parent
path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else root / "pyproject.toml"
text = path.read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
print(match.group(1) if match else "0.0.0")
