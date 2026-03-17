"""
Compiles all .ts translation files to .qm using lrelease.
Run from anywhere: python scripts/release_translations.py
"""

import subprocess
import sys
from pathlib import Path

TRANSLATIONS_DIR = Path(__file__).parent.parent / "src" / "gui" / "translations"

def find_lrelease():
    import shutil
    for candidate in ["lrelease", "lrelease-qt5"]:
        path = shutil.which(candidate)
        if path:
            return path
    return None

def main():
    lrelease = find_lrelease()
    if not lrelease:
        print("Error: lrelease not found. Install Qt tools:")
        print("  Arch Linux:    sudo pacman -S qt5-tools")
        print("  Ubuntu/Debian: sudo apt install qttools5-dev-tools")
        sys.exit(1)

    ts_files = sorted(TRANSLATIONS_DIR.glob("*.ts"))
    if not ts_files:
        print(f"No .ts files found in {TRANSLATIONS_DIR}")
        sys.exit(1)

    print(f"Found {len(ts_files)} translation file(s):")
    ok = 0
    fail = 0
    for ts in ts_files:
        qm = ts.with_suffix(".qm")
        result = subprocess.run([lrelease, str(ts), "-qm", str(qm)], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  OK  {ts.name} -> {qm.name}")
            ok += 1
        else:
            print(f"  FAIL {ts.name}")
            print(result.stderr.strip())
            fail += 1

    print(f"\n{ok} compiled, {fail} failed.")
    sys.exit(1 if fail else 0)

if __name__ == "__main__":
    main()
