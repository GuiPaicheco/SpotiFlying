"""Resolve DLL collisions caused by PyInstaller's transitive dependency scan."""
import ssl
from pathlib import Path
from shutil import copyfile

import pefile

internal = Path("dist/SpotiFlying/_internal")

# Some Python runtimes load this distrust list beside ssl.py on every TLS context.
distrust_list = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
if distrust_list.is_file():
    copyfile(distrust_list, internal / distrust_list.name)
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
