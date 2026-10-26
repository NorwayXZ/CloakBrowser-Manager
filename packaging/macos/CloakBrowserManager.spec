# PyInstaller spec for the macOS app bundle. Run through build-dmg.sh.
# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]
BUILD_DIR = ROOT / "build" / "macos"
APP_NAME = "CloakBrowser Manager"
VERSION = os.environ.get("CLOAKBROWSER_APP_VERSION", "0.0.0")
BUILD_NUMBER = os.environ.get("CLOAKBROWSER_APP_BUILD", "0")

hiddenimports = (
    collect_submodules("backend", filter=lambda name: ".tests" not in name)
    + collect_submodules("uvicorn")
    + collect_submodules("cloakbrowser")
    + ["AppKit", "Foundation", "WebKit", "PyObjCTools.AppHelper", "objc", "panel_window"]
)

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "docs" / "AGENT.md"), "docs"),
    (str(BUILD_DIR / "app_version.json"), "."),
]
datas += collect_data_files("cloakbrowser")
for package in ("cloakbrowser", "playwright", "fastapi", "uvicorn", "pydantic", "geoip2", "maxminddb"):
    datas += copy_metadata(package)

a = Analysis(
    [str(ROOT / "packaging" / "macos" / "app_main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    argv_emulation=False,
    codesign_identity=None,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(BUILD_DIR / "AppIcon.icns"),
    bundle_identifier="io.github.norwayxz.cloakbrowser-manager",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": BUILD_NUMBER,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.utilities",
    },
)
