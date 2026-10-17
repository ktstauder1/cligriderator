# Executed by PyInstaller on macOS. All paths are resolved at build time.
import os
from pathlib import Path
import platform
import subprocess
import sys

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.osx import BUNDLE
from PyInstaller.config import CONF

if sys.platform != "darwin":
    raise RuntimeError("The standalone app must be built on macOS")

macos = Path(CONF["specpath"])
root = macos.parent.parent
build = Path(os.environ["CLIGRID_BUILD_ROOT"])
prefix = Path(subprocess.check_output(["brew", "--prefix"], text=True).strip())
ncurses = Path(subprocess.check_output(["brew", "--prefix", "ncurses"], text=True).strip())
version = subprocess.check_output([sys.executable, str(root / "packaging/version.py")], text=True).strip()

a = Analysis(
    [str(macos / "standalone_entry.py")],
    pathex=[str(root)],
    binaries=[(str(prefix / "bin/tmux"), "bin")],
    datas=[
        (str(root / "icons"), "icons"),
        (str(root / "LICENSE"), "."),
        (str(build / "notices"), "ThirdPartyNotices"),
        (str(ncurses / "share/terminfo"), "share/terminfo"),
    ],
    hiddenimports=[path.stem for path in root.glob("cligrid*.py")],
    hookspath=[str(macos / "hooks")],
    hooksconfig={"gi": {"module-versions": {"Gtk": "3.0", "Gdk": "3.0"},
                        "icons": ["Adwaita", "hicolor"], "themes": ["Adwaita"]}},
    excludes=["tkinter", "pytest", "unittest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="cligrid", console=False,
    strip=False, upx=False, target_arch=platform.machine(),
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="cligrid")
app = BUNDLE(
    collection, name="Cli Griderator.app", icon=str(build / "cligrid.icns"),
    bundle_identifier="com.konatus.cligrid", version=version,
    info_plist={
        "CFBundleDisplayName": "Cli Griderator",
        "CFBundleShortVersionString": version,
        # Build-host minimum is deliberately conservative; dependencies may
        # require more than Python's own minimum deployment target.
        "LSMinimumSystemVersion": platform.mac_ver()[0],
        "NSHighResolutionCapable": True,
        "NSDisablePersistence": True,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    },
)
