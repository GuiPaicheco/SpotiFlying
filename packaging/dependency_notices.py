"""Copy licenses shipped with the frozen Python dependencies."""
import shutil
import sys
from importlib import metadata
from pathlib import Path

root = Path("dist/SpotiFlying/licenses")
root.mkdir(exist_ok=True, parents=True)
for distribution in metadata.distributions():
    name = distribution.metadata["Name"]
    if not name.lower().startswith(("pyside6", "shiboken6", "winrt", "pyinstaller", "typing")):
        continue
    for entry in distribution.files or ():
        if ".dist-info/" in entry.as_posix() and "license" in entry.as_posix().lower():
            target = root / name / entry.name
            target.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(entry.locate(), target)

python_home = Path(sys.base_prefix)
for candidate in (python_home / "LICENSE.txt", python_home / "LICENSE", Path("packaging/licenses/Python.txt")):
    if candidate.exists():
        shutil.copyfile(candidate, root / "Python.txt")
        break
else:
    raise FileNotFoundError("Python license")

for entry in Path("packaging/licenses").glob("*.txt"):
    if entry.name != "Python.txt":
        shutil.copyfile(entry, root / entry.name)
shutil.copyfile("src/spotiflying/assets/BarlowCondensed-OFL.txt", root / "BarlowCondensed-OFL.txt")
