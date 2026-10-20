"""Build the bundled local Python service with PyInstaller."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
NAME = "sec-studio-engine"


def main() -> int:
    try:
        import PyInstaller.__main__
    except ImportError:
        print("PyInstaller is required. Install it with: python -m pip install pyinstaller", file=sys.stderr)
        return 2
    separator = ";" if os.name == "nt" else ":"
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", NAME,
        "--specpath", str(HERE / "build-specs"),
        "--distpath", str(HERE / "dist-engine"),
        "--workpath", str(HERE / "build-engine"),
        "--paths", str(BACKEND),
        "--add-data", f"{BACKEND / 'templates'}{separator}templates",
        "--add-data", f"{BACKEND / 'static'}{separator}static",
        str(BACKEND / "app.py"),
    ]
    return subprocess.call(command, cwd=BACKEND)


if __name__ == "__main__":
    raise SystemExit(main())
