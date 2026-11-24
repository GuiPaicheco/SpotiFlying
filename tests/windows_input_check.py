"""Interactive Windows acceptance check with a separate process receiving input."""
import ctypes
import json
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from types import SimpleNamespace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QPlainTextEdit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spotiflying.app import Controller  # noqa: E402
from spotiflying.platform import user32  # noqa: E402

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


class Receiver(QPlainTextEdit):
    def __init__(self, output):
        super().__init__()
        self.output = output
        self.events = []
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setPlainText("\n".join(f"Linha fictícia {i}" for i in range(120)))

    def record(self, name):
        self.events.append(name)
        self.output.write_text(json.dumps({"pid": os.getpid(), "events": self.events}), encoding="utf-8")

    def mousePressEvent(self, event):
        self.record("press")
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        self.record("scroll")
        super().wheelEvent(event)


def pid_at(x, y):
    result = wintypes.DWORD()
    hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(result))
    return result.value


def points_for(window, alpha):
    rect = wintypes.RECT()
    user32.GetWindowRect(int(window.winId()), ctypes.byref(rect))
    return [(rect.left + x, rect.top + y) for x, y in alpha]


def verify(qt, root, report):
    target = root / "receiver.json"
    process = subprocess.Popen([sys.executable, __file__, "--receiver", str(target)])
    options = SimpleNamespace(smoke=True, capture=None, probe=None, demo=True, tray=True)
    controller = Controller(qt, options, root / "profile")
    cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    state = {}
    deadline = monotonic() + 24
    foreground = user32.GetForegroundWindow()

    def act():
        if not target.exists():
            if process.poll() is None and monotonic() < deadline:
                QTimer.singleShot(300, act)
                return
            finish()
            return
        controller.lyric_window.raise_()
        controller.card_window.raise_()
        controller.lyric_window.apply_native()
        controller.card_window.apply_native()
        controller.command("seek", 1000)
        QTimer.singleShot(300, input_phase)

    def input_phase():
        receiver_pid = json.loads(target.read_text(encoding="utf-8"))["pid"]
        lyric, card = controller.lyric_window, controller.card_window
        im = lyric.grab().toImage()
        glyph = next(((x, y) for y in range(2, min(im.height(), 100))
                      for x in range(2, min(im.width(), 500)) if im.pixelColor(x, y).alpha() >= 250), None)
        if glyph is None:
            finish()
            return
        coords = points_for(lyric, [glyph, (im.width() - 15, im.height() - 15)])
        coords += points_for(card, [(24, 25)])
        for scenario, (x, y) in zip(("glyph", "empty", "card"), coords):
            state[scenario] = pid_at(x, y) == receiver_pid
            if state[scenario]:
                user32.SetCursorPos(x, y)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
        x, y = coords[0]
        if state["glyph"] and pid_at(x, y) == receiver_pid:
            user32.SetCursorPos(x, y)
            user32.mouse_event(0x0800, 0, 0, -120, 0)
        QTimer.singleShot(500, finish)

    def finish():
        try:
            events = json.loads(target.read_text(encoding="utf-8"))["events"] if target.exists() else []
        except (OSError, ValueError):
            events = []
        user32.SetCursorPos(cursor.x, cursor.y)
        if process.poll() is None:
            process.terminate()
            process.wait(3)
        if foreground:
            user32.SetForegroundWindow(foreground)
        checks = {"points": state, "cross_process_styles": all(state.get(k, False) for k in ("glyph", "empty", "card")),
                  "click_events": events.count("press"), "wheel_events": events.count("scroll")}
        checks["ok"] = checks["cross_process_styles"] and checks["click_events"] == 3 and checks["wheel_events"] == 1
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(checks, indent=2), encoding="utf-8")
        qt.exit(0 if checks["ok"] else 1)

    QTimer.singleShot(1200, act)


if __name__ == "__main__":
    app = QApplication([sys.argv[0]])
    if len(sys.argv) == 3 and sys.argv[1] == "--receiver":
        receiver = Receiver(Path(sys.argv[2]))
        receiver.setGeometry(app.primaryScreen().availableGeometry())
        receiver.show()
        receiver.raise_()
        receiver.activateWindow()
        QTimer.singleShot(300, lambda: receiver.record("ready"))
        QTimer.singleShot(30000, app.quit)
        raise SystemExit(app.exec())
    with TemporaryDirectory(prefix="SpotiFlying-Input-") as isolated:
        verify(app, Path(isolated), Path(sys.argv[1]).resolve())
        raise SystemExit(app.exec())
