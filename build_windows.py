#!/usr/bin/env python3
"""Сборка одного portable EXE. Запускать Python из .venv проекта."""
from pathlib import Path
import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent
PyInstaller.__main__.run([
    str(ROOT / "desktop.py"),
    "--name=LLM Bench",
    "--onefile",
    "--windowed",
    "--clean",
    "--noconfirm",
    "--noupx",
    f"--icon={ROOT / 'assets' / 'icon.ico'}",
    f"--version-file={ROOT / 'assets' / 'version_info.txt'}",
    f"--add-data={ROOT / 'web'};web",
    f"--add-data={ROOT / 'public_data'};public_data",
    "--collect-submodules=webview.platforms",
    f"--distpath={ROOT / 'dist'}",
    f"--workpath={ROOT / 'build' / 'windows'}",
    f"--specpath={ROOT / 'build'}",
])
