"""Process CPU and working set measurements for the source build on Windows."""
import ctypes
import json
import os
import platform
import sys
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, process_time
from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spotiflying.app import Controller  # noqa: E402


class ProcessMemory(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged",
                                            "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")
    ]


def memory():
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    stats = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    stats.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
    values = ProcessMemory(size=ctypes.sizeof(ProcessMemory))
    if not stats(kernel.GetCurrentProcess(), ctypes.byref(values), values.size):
        raise ctypes.WinError()
    return round(values.working / 1024 ** 2, 2)


def benchmark(qt, root, output):
    options = SimpleNamespace(smoke=True, capture=None, probe=None, tray=True, demo=True)
    controller = Controller(qt, options, root)
    results = {}
    duration = 10
    phases = iter(("idle_paused", "playing_visible", "playing_hidden"))

    def next_phase():
        try:
            name = next(phases)
        except StopIteration:
            output.parent.mkdir(exist_ok=True, parents=True)
            output.write_text(json.dumps({"os": platform.version(), "logical_cpus": os.cpu_count(),
                                          "duration_seconds_per_phase": duration, "process": "source",
                                          "results": results}, indent=2), encoding="utf-8")
            qt.quit()
            return
        if name == "idle_paused":
            controller.command("pause")
        elif name == "playing_visible":
            controller.command("play")
        else:
            controller.toggle_layers()
        start_cpu, start_time = process_time(), monotonic()

        def sample():
            elapsed = monotonic() - start_time
            results[name] = {"cpu_percent_one_core": round((process_time() - start_cpu) / elapsed * 100, 2),
                             "working_set_mib": memory()}
            next_phase()

        QTimer.singleShot(duration * 1000, sample)

    QTimer.singleShot(500, next_phase)


def endurance(qt, root, output):
    options = SimpleNamespace(smoke=True, capture=None, probe=None, tray=True, demo=True)
    controller = Controller(qt, options, root)
    controller.toggle_layers()
    start = monotonic()
    samples = []
    transitions = 0
    timer = QTimer(qt, interval=5000)

    def switch():
        nonlocal transitions
        controller.command("next")
        transitions += 1

    def sample():
        elapsed = round(monotonic() - start, 1)
        samples.append({"seconds": elapsed, "track_changes": transitions, "working_set_mib": memory()})
        output.parent.mkdir(exist_ok=True, parents=True)
        output.write_text(json.dumps({"os": platform.version(), "process": "source",
                                      "hidden": True, "complete": elapsed >= 1800, "samples": samples},
                                     indent=2), encoding="utf-8")
        if elapsed >= 1800:
            timer.stop()
            qt.quit()
        else:
            QTimer.singleShot(min(60_000, max(250, round((1800 - elapsed) * 1000))), sample)

    timer.timeout.connect(switch)
    timer.start()
    sample()


if __name__ == "__main__":
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    with TemporaryDirectory(prefix="SpotiFlying-Bench-") as profile:
        measure = endurance if "--endurance" in sys.argv[2:] else benchmark
        measure(app, Path(profile), Path(sys.argv[1]).resolve())
        raise SystemExit(app.exec())
