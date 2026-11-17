import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "elda_qgis"
PROFILE_TAIL = Path("QGIS3/profiles/default/python/plugins")


def plugins_dir():
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support/QGIS"
    elif sys.platform == "win32":
        base = Path(os.environ["APPDATA"]) / "QGIS"
    else:
        base = Path.home() / ".local/share/QGIS"
    return base / PROFILE_TAIL


def main():
    parser = argparse.ArgumentParser(description="Link elda_qgis into the QGIS profile")
    parser.add_argument("--dry-run", action="store_true", help="print what would be done")
    args = parser.parse_args()

    target = plugins_dir() / "elda_qgis"
    if target.is_symlink() and target.resolve() == SOURCE:
        print(f"Already linked: {target} -> {SOURCE}")
        return 0
    if target.exists() or target.is_symlink():
        print(f"Refusing to overwrite {target}", file=sys.stderr)
        print("The plugin is already installed there (from a zip). Uninstall it in QGIS", file=sys.stderr)
        print("(Extensions > Installer/Gérer les extensions > Installées > ELDA > Désinstaller), then run again.", file=sys.stderr)
        return 1
    print(f"Link {target} -> {SOURCE}")
    if not args.dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(SOURCE, target_is_directory=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
