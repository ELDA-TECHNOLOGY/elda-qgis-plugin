import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "elda_qgis"


def _version():
    sys.path.insert(0, str(ROOT))
    from elda_qgis.version import VERSION

    return VERSION


def build(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / f"elda_qgis-{_version()}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(PLUGIN.rglob("*")):
            rel = f.relative_to(PLUGIN)
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc" and not any(p.startswith(".") for p in rel.parts):
                z.write(f, f.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    Path(f"{zip_path}.sha256").write_text(f"{digest}  {zip_path.name}\n")
    return str(zip_path)


if __name__ == "__main__":
    print(build(ROOT / "dist"))
