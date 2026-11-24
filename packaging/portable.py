from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path("dist")
target = Path("release")
target.mkdir(exist_ok=True)
with ZipFile(target / "SpotiFlying-Portable-x64.zip", "w", ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted((root / "SpotiFlying").rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(root).as_posix())
    archive.writestr("SpotiFlying/portable.flag", "SpotiFlying portable\n")
