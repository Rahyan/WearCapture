from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_pyinstaller(name: str, entry_script: str, windowed: bool) -> None:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        name,
    ]
    if windowed:
        cmd.append("--windowed")
    cmd.append(str(ROOT / entry_script))

    subprocess.run(cmd, cwd=ROOT, check=True)


def clean_build_dirs() -> None:
    for folder in [ROOT / "build", ROOT / "dist"]:
        if folder.exists():
            shutil.rmtree(folder)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build WearCapture binaries with PyInstaller")
    parser.add_argument("--cli", action="store_true", help="Build CLI binary")
    parser.add_argument("--ui", action="store_true", help="Build desktop UI binary")
    parser.add_argument("--clean", action="store_true", help="Remove old build/dist first")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    build_cli = args.cli or (not args.cli and not args.ui)
    build_ui = args.ui or (not args.cli and not args.ui)

    if args.clean:
        clean_build_dirs()

    if build_cli:
        run_pyinstaller(name="wearcapture-cli", entry_script="scripts/entry_cli.py", windowed=False)
    if build_ui:
        run_pyinstaller(name="wearcapture-ui", entry_script="scripts/entry_ui.py", windowed=True)

    print("Build complete. See dist/ for output binaries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
