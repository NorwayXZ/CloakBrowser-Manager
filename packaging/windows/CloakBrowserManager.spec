# PyInstaller spec for the Windows app. Run through build-installer.ps1.
# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]
BUILD_DIR = ROOT / "build" / "windows"
APP_NAME = "CloakBrowser Manager"

hiddenimports = (
    collect_submodules("backend", filter=lambda name: ".tests" not in name)
    + collect_submodules("uvicorn")
    + collect_submodules("cloakbrowser")
    + collect_submodules("pystray")
)

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "docs" / "AGENT.md"), "docs"),
    (str(BUILD_DIR / "app_version.json"), "."),
    (str(BUILD_DIR / "app_icon.png"), "."),
]
datas += collect_data_files("cloakbrowser")
for package in ("cloakbrowser", "playwright", "fastapi", "uvicorn", "pydantic", "geoip2", "maxminddb"):
    datas += copy_metadata(package)

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "app_main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
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
    icon=str(BUILD_DIR / "AppIcon.ico"),
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
