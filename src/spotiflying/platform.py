"""Windows window styles, process-wide hotkeys, and per-user startup."""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QSettings
from PySide6.QtGui import QKeySequence

WINDOWS = sys.platform == "win32"
if WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]


def overlay_styles(hwnd, passive, topmost):
    if not WINDOWS:
        return
    position = -20
    layered, transparent, tool, noactivate, app = 0x80000, 0x20, 0x80, 0x08000000, 0x40000
    style = user32.GetWindowLongPtrW(hwnd, position)
    wanted = (style | layered | tool) & ~app
    wanted = wanted | transparent | noactivate if passive else wanted & ~(transparent | noactivate)
    if wanted != style:
        user32.SetWindowLongPtrW(hwnd, position, wanted)
        if user32.GetWindowLongPtrW(hwnd, position) != wanted:
            raise OSError("Falha ao configurar a janela de sobreposição")
    user32.SetWindowPos(hwnd, -1 if topmost else -2, 0, 0, 0, 0, 0x0033)


def hotkey_codes(sequence):
    parsed = QKeySequence.fromString(sequence, QKeySequence.SequenceFormat.PortableText)
    if parsed.count() != 1:
        raise ValueError("Use uma combinação, como Ctrl+Alt+L.")
    item = parsed[0]
    qt_flags = item.keyboardModifiers().value
    mods = sum(win for qt, win in ((0x02000000, 4), (0x04000000, 2), (0x08000000, 1), (0x10000000, 8))
               if qt_flags & qt)
    key = item.key().value
    if 0x01000030 <= key <= 0x01000047:
        key = 0x70 + key - 0x01000030
    elif not (0x30 <= key <= 0x39 or 0x41 <= key <= 0x5A):
        raise ValueError("Use uma letra, um número ou uma tecla F1–F24.")
    if not mods:
        raise ValueError("Inclua Ctrl, Alt, Shift ou Meta.")
    return mods | 0x4000, key


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self):
        super().__init__()
        self.items = {}
        self.counter = 100

    def configure(self, action, sequence, callback):
        if not WINDOWS:
            return
        old = self.items.get(action)
        if old and old[1] == sequence:
            return
        if sequence:
            mods, key = hotkey_codes(sequence)
            self.counter += 1
            if not user32.RegisterHotKey(None, self.counter, mods, key):
                reason = ctypes.get_last_error()
                raise ValueError(f"O Windows recusou a combinação (erro {reason}).")
        if old:
            user32.UnregisterHotKey(None, old[0])
            del self.items[action]
        if sequence:
            self.items[action] = (self.counter, sequence, callback)

    def nativeEventFilter(self, event_type, message):
        if WINDOWS and bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            event = wintypes.MSG.from_address(int(message))
            if event.message == 0x0312:
                for hotkey, _, callback in self.items.values():
                    if hotkey == event.wParam:
                        callback()
                        return True, 0
        return False, 0

    def close(self):
        for action in tuple(self.items):
            self.configure(action, "", None)


def startup(enabled, command):
    if WINDOWS:
        store = QSettings(r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
                          QSettings.Format.NativeFormat)
        if enabled:
            store.setValue("SpotiFlying", command)
        else:
            store.remove("SpotiFlying")
        store.sync()
        if store.status() != QSettings.Status.NoError:
            raise OSError("O Windows recusou a configuração de inicialização.")
