"""Resolve DLL collisions caused by PyInstaller's transitive dependency scan."""
from pathlib import Path
from shutil import copyfile

import pefile

internal = Path("dist/SpotiFlying/_internal")
icu = internal / "icuuc.dll"
if icu.is_file():
    library = pefile.PE(icu, fast_load=True)
    library.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
    exports = {symbol.name for symbol in library.DIRECTORY_ENTRY_EXPORT.symbols}
    library.close()
    if b"ucnv_open" not in exports:
        # Qt uses the Windows ICU ABI. Standalone Python can include a versioned ICU for SQLite.
        icu.unlink()
        for data in internal.glob("icudt[0-9]*.dll"):
            data.unlink()

runtime = internal / "PySide6" / "MSVCP140.dll"
copyfile(runtime, internal / runtime.name)
winrt = internal / "winrt" / runtime.name
if winrt.is_file():
    copyfile(runtime, winrt)
