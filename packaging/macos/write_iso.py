#!/usr/bin/env python3
"""Write a Joliet + Rock Ridge ISO that Finder mounts when named .dmg."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("dest")
    parser.add_argument("--volume", default="Cli Griderator")
    args = parser.parse_args()
    try:
        import pycdlib
    except ImportError:
        sys.exit("pycdlib is required: python3 -m pip install --user pycdlib")

    src = Path(args.source).resolve()
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident=args.volume[:32])
    serial = 0

    def next_iso(is_dir=False):
        nonlocal serial
        serial += 1
        name = f"F{serial:05d}"
        return f"/{name}" if is_dir else f"/{name}.;1"

    def add_tree(disk: Path, iso_dir: str, joliet_dir: str):
        children = sorted(disk.iterdir(), key=lambda p: p.name.lower())
        for child in children:
            rr = child.name
            joliet = (joliet_dir.rstrip("/") + "/" + rr) if joliet_dir != "/" else "/" + rr
            if child.is_dir():
                iso_path = next_iso(True)
                iso.add_directory(iso_path, rr_name=rr, joliet_path=joliet)
                add_tree(child, iso_path, joliet)
                continue
            if not child.is_file():
                continue
            mode = 0o0100755 if (child.stat().st_mode & 0o111) else 0o0100644
            iso.add_file(
                str(child),
                next_iso(),
                rr_name=rr,
                joliet_path=joliet,
                file_mode=mode,
            )

    add_tree(src, "/", "/")
    Path(args.dest).parent.mkdir(parents=True, exist_ok=True)
    iso.write(args.dest)
    iso.close()


if __name__ == "__main__":
    main()
