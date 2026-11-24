"""Qt process and window lifecycle."""
import argparse
import ctypes
import hashlib
import logging
import os
import subprocess
import sys
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__
from .content import Content
from .desktop import Desktop
from .lyrics import Lyrics, LyricsProvider
from .overlay import CardOverlay, LyricOverlay, active_screen, geometry
from .platform import Hotkeys, startup
from .playback import PlaybackProvider
from .settings import DEFAULT, PRESETS, STORIES, Settings, visual_settings
from .sync import Playhead
from .ui import SettingsWindow

ASSETS = Path(__file__).parent / "assets"


class Controller(QObject, Content, Desktop):
    fetched = Signal(int, object, object, str)
    release_checked = Signal(object)

    def __init__(self, qt, options, isolated=None):
        super().__init__()
        self.qt, self.options = qt, options
        self.store = Settings(isolated)
        self.data = self.store.data
        self.default_screen = active_screen().name()
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.log = RotatingFileHandler(self.store.root / "spotiflying.log", maxBytes=200_000,
                                       backupCount=2, encoding="utf-8")
        self.log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger("spotiflying").addHandler(self.log)
        logging.getLogger("spotiflying").setLevel(logging.INFO)
        self.icon = QIcon(str(ASSETS / "spotiflying.ico"))
        qt.setWindowIcon(self.icon)
        self.snapshot = self.last_spotify = None
        self.playhead = Playhead()
        self.lyrics = Lyrics("missing")
        self.candidates = []
        self.cache, self.choices = OrderedDict(), OrderedDict()
        self.generation = 0
        self.provider_status = self.error = ""
        self.demo = self.demo_repeat = self.demo_shuffle = False
        self.demo_index = 0
        self.demo_playing = self.jump = True
        self.interaction = self.editing = self.force_card = False
        self.last_interaction = self.last_tick = monotonic()
        self.last_index = -1
        self.watches = set()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="spotiflying")
        self.catalog = LyricsProvider()
        self.fetched.connect(self.receive_lyrics)
        self.release_checked.connect(self.show_update_result)
        self.lyric_window = LyricOverlay(self.data["visual"])
        self.card_window = CardOverlay(self.data["visual"], str(ASSETS / "spotiflying.ico"))
        self.card_window.command.connect(self.command)
        self.card_window.activity.connect(self.activity)
        for window in (self.lyric_window, self.card_window):
            window.cancel.connect(self.cancel_mode)
        self.settings_ui = SettingsWindow(self, self.icon)
        self.hotkeys = Hotkeys()
        qt.installNativeEventFilter(self.hotkeys)
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("SpotiFlying")
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activation)
        self.tray.show()
        self.provider = PlaybackProvider()
        self.provider.snapshot.connect(self.spotify_snapshot)
        self.provider.status.connect(self.set_provider_status)
        self.provider.command_failed.connect(self.notify)
        self.save_timer = QTimer(singleShot=True, interval=250)
        self.save_timer.timeout.connect(self.save)
        self.retry_timer = QTimer(singleShot=True)
        self.retry_timer.timeout.connect(lambda: self.reload_lyrics(True))
        self.tick_timer = QTimer(timerType=Qt.TimerType.PreciseTimer)
        self.tick_timer.timeout.connect(self.tick)
        qt.screenAdded.connect(self.screen_changed)
        qt.screenRemoved.connect(self.screen_changed)
        qt.aboutToQuit.connect(self.close)
        for screen in qt.screens():
            self.watch_screen(screen)
        if isolated is None:
            for key in ("toggle_hotkey", "interact_hotkey"):
                try:
                    self.register(key, self.data[key])
                except ValueError as error:
                    self.notify(str(error))
        self.sync_ui()
        if options.demo:
            self.set_demo(True)
        if not options.demo or options.probe:
            self.provider.start()
        if not options.tray and isolated is None:
            self.open_settings()
            if not self.data["intro_seen"]:
                QTimer.singleShot(250, self.intro)

    def watch_screen(self, screen):
        if screen not in self.watches:
            self.watches.add(screen)
            screen.availableGeometryChanged.connect(self.screen_changed)
            screen.logicalDotsPerInchChanged.connect(self.screen_changed)

    def screen_changed(self, *_):
        self.watches.intersection_update(self.qt.screens())
        for screen in self.qt.screens():
            self.watch_screen(screen)
        if not self.editing:
            QTimer.singleShot(0, self.place)
            QTimer.singleShot(0, self.settings_ui.refresh_monitors)

    def screen(self, placement):
        names = [placement.get("screen"), self.data["monitor"], self.default_screen]
        for name in names:
            for screen in self.qt.screens():
                if screen.name() == name:
                    return screen
        screen = active_screen()
        self.default_screen = screen.name()
        return screen

    def place(self):
        visual = self.data["visual"]
        for window in (self.lyric_window, self.card_window):
            placement = self.data[window.kind + "_position"]
            area = self.screen(placement).availableGeometry()
            if window.kind == "lyrics":
                width, height = visual["width"], visual["height"]
                if visual["units"] == "Percentual":
                    width, height = round(area.width() * width / 100), round(area.height() * height / 100)
                size = QSize(max(110, width), max(44, height))
            else:
                controls = (74 if visual["card_interactive_controls"] else 24) if self.interaction else (
                    29 if "Controles" in visual["card_items"] else 0)
                size = QSize(visual["card_width"], visual["card_height"] + controls)
            window.setGeometry(geometry(area, size, placement, window.kind))

    def register(self, key, sequence):
        self.hotkeys.configure(key, sequence, self.toggle_layers if key == "toggle_hotkey" else self.toggle_interaction)

    def save_later(self):
        self.save_timer.start()

    def save(self):
        try:
            self.store.save()
        except OSError:
            self.notify("Não foi possível gravar as configurações.")
            logging.getLogger(__name__).error("Gravação de configurações recusada")

    def change(self, key, value, visual):
        try:
            if key.endswith("_hotkey"):
                self.register(key, value)
            elif key == "startup":
                command = [sys.executable, "--tray"] if getattr(sys, "frozen", False) else (
                    [sys.executable, str(Path(__file__).parents[2] / "packaging" / "launcher.py"), "--tray"])
                startup(value, subprocess.list2cmdline(command))
        except (ValueError, OSError) as error:
            self.notify(str(error))
            self.settings_ui.refresh()
            return
        if visual:
            self.store.update_visual(key, value)
            self.data["visual"] = visual_settings(self.data["visual"])
        elif key == "preset":
            self.store.preset(value)
        else:
            self.data[key] = value
        if key == "monitor":
            for position in ("lyrics_position", "card_position"):
                if self.data[position]:
                    self.data[position]["screen"] = value
        if key == "catalog":
            self.retry_timer.stop()
            self.reload_lyrics()
        if key == "persistent":
            self.interaction = bool(value)
        self.force_card = key == "card_visible" and bool(value)
        self.save_later()
        self.sync_ui()

    def change_card_items(self, order, active):
        self.store.update_visual("item_order", order)
        self.store.update_visual("card_items", active)
        self.save_later()
        self.sync_ui(refresh=False)

    def sync_ui(self, refresh=True):
        if refresh:
            self.settings_ui.refresh()
        visual = self.data["visual"]
        self.lyric_window.visual = self.card_window.visual = visual
        self.lyric_window.cache.clear()
        self.lyric_window.update()
        self.card_window.paint_key = None
        if not self.editing:
            self.place()
        self.update_visibility()
        self.make_menu()
        self.tick()

    def update_visibility(self):
        data, visual = self.data, self.data["visual"]
        self.lyric_window.mode("edit" if self.editing else "passive", data["topmost"])
        self.card_window.mode("edit" if self.editing else "interactive" if self.interaction else "passive",
                              data["topmost"])
        self.lyric_window.setVisible(self.editing or data["lyrics_visible"])
        hide = visual["autohide"]
        idle = monotonic() - self.last_interaction >= data["interaction_seconds"]
        no_playback = not self.snapshot or not self.snapshot.timeline.playing
        hidden = (hide == "Sem reprodução" and no_playback or hide == "Inatividade" and idle
                  or hide == "Cursor fora" and self.interaction and idle and not self.card_window.underMouse())
        self.card_window.setVisible(self.editing or data["card_visible"] and (self.force_card or not hidden))
        self.provider.visible = not data["economy"] and (
            self.lyric_window.isVisible() or self.card_window.isVisible())

    def toggle_layers(self):
        target = not (self.data["lyrics_visible"] or self.data["card_visible"])
        self.data["lyrics_visible"] = self.data["card_visible"] = target
        self.force_card = target
        self.save_later()
        self.sync_ui()

    def activity(self):
        self.last_interaction = monotonic()
        self.force_card = False

    def toggle_interaction(self):
        if self.editing:
            self.cancel_mode()
        self.interaction = not self.interaction
        if self.interaction:
            self.data["card_visible"] = True
            self.activity()
            self.force_card = True
        self.sync_ui()
        if self.interaction:
            self.card_window.raise_()
            self.card_window.activateWindow()
            self.card_window.buttons["play"].setFocus()

    def edit_position(self):
        self.interaction = False
        self.editing = True
        self.edit_origins = {window.kind: window.pos() for window in (self.lyric_window, self.card_window)}
        self.sync_ui()
        box = QMessageBox(self.settings_ui)
        box.setWindowTitle("Editar posição")
        box.setText("Arraste as sobreposições e redimensione pelo canto verde.")
        box.setWindowModality(Qt.WindowModality.NonModal)
        confirm = box.addButton("Confirmar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.finished.connect(lambda _: self.confirm_position() if box.clickedButton() == confirm
                             else self.cancel_mode())
        self.edit_box = box
        box.show()

    def finish_edit(self):
        self.editing = False
        if getattr(self, "edit_box", None):
            box, self.edit_box = self.edit_box, None
            box.finished.disconnect()
            box.hide()
            box.deleteLater()

    def confirm_position(self):
        if not self.editing:
            return
        windows = (self.lyric_window, self.card_window)
        if self.data["group"]:
            moved = max(windows, key=lambda window: (window.pos() - self.edit_origins[window.kind]).manhattanLength())
            delta = moved.pos() - self.edit_origins[moved.kind]
            for window in windows:
                window.move(self.edit_origins[window.kind] + delta)
        for window in windows:
            screen = self.qt.screenAt(window.geometry().center()) or active_screen()
            area = screen.availableGeometry()
            place = geometry(area, window.size(), {"anchor": "tl", "x": window.x() - area.x(),
                                                   "y": window.y() - area.y()}, window.kind)
            self.data[window.kind + "_position"] = {
                "screen": screen.name(), "anchor": "tl", "x": place.x() - area.x(), "y": place.y() - area.y(),
            }
            dimensions = {"width": min(place.width(), 2400), "height": min(place.height(), 1800), "units": "DIP"}
            if window.kind == "card":
                dimensions = {"card_width": min(place.width(), 800), "card_height": min(place.height(), 480)}
            for key, value in dimensions.items():
                self.store.update_visual(key, value)
        self.finish_edit()
        self.save_later()
        self.sync_ui()

    def cancel_mode(self):
        self.finish_edit()
        self.interaction = self.force_card = False
        self.sync_ui()

    def center(self):
        screen = active_screen().name()
        self.data["lyrics_position"] = {"screen": screen, "anchor": "center", "x": 0, "y": -18}
        self.data["card_position"] = {"screen": screen, "anchor": "center", "x": 0, "y": 90}
        self.save_later()
        self.sync_ui()

    def set_anchor(self, kind, anchor):
        key = kind + "_position"
        window = self.lyric_window if kind == "lyrics" else self.card_window
        area = self.screen(self.data[key]).availableGeometry()
        reference = geometry(area, window.size(), {"anchor": anchor, "x": 0, "y": 0}, kind)
        self.data[key] = {"screen": self.screen(self.data[key]).name(), "anchor": anchor,
                          "x": window.x() - reference.x(), "y": window.y() - reference.y()}
        self.save_later()
        self.sync_ui()

    def restore_reference(self):
        self.store.preset("Stories", clear=True)
        for key in ("lyrics_position", "card_position", "lyrics_visible", "card_visible", "topmost", "group", "persistent"):
            self.data[key] = deepcopy(DEFAULT[key])
        self.cancel_mode()
        self.save_later()

    def reset_preset(self):
        self.store.preset(self.data["preset"], clear=True)
        self.save_later()
        self.sync_ui()

    def reset_section(self, visual, *keys):
        default = {**STORIES, **PRESETS[self.data["preset"]]} if visual else DEFAULT
        for key in keys:
            self.change(key, deepcopy(default[key]), visual)

    def reset_all(self):
        if QMessageBox.question(self.settings_ui, "Redefinir configurações",
                                "Redefinir o visual, desvincular letras e apagar o histórico?") != QMessageBox.StandardButton.Yes:
            return
        old = {key: self.data[key] for key in ("toggle_hotkey", "interact_hotkey", "startup")}
        self.data.clear()
        self.data.update(deepcopy(DEFAULT))
        for key, value in old.items():
            target = self.data[key]
            self.data[key] = value
            self.change(key, target, False)
        self.clear_cache()
        self.reload_lyrics()
        self.restore_reference()

    def tick(self):
        now = monotonic()
        interrupted = now - self.last_tick > 3
        self.last_tick = now
        if interrupted and not self.demo:
            self.provider.wake()
        idle = now - self.last_interaction >= self.data["interaction_seconds"]
        if self.interaction and idle and not self.data["persistent"] and not self.options.capture:
            self.interaction = self.force_card = False
            self.place()
            self.make_menu()
        self.update_visibility()
        playing = bool(self.snapshot and self.snapshot.timeline.playing)
        visible = self.lyric_window.isVisible() or self.card_window.isVisible()
        fps = min(12, self.data["fps"]) if self.data["economy"] else self.data["fps"]
        interval = round(1000 / fps) if playing and visible else 250 if self.interaction else 500
        if self.tick_timer.interval() != interval or not self.tick_timer.isActive():
            self.tick_timer.start(interval)
        position = self.playhead.position()
        duration = self.snapshot.timeline.duration if self.snapshot else 0
        if self.demo and playing and duration and position is not None and position >= duration:
            if self.demo_repeat:
                self.demo_snapshot(0, True)
            else:
                self.command("next")
            return
        self.paint_position(position, duration, playing, interrupted)

    def close(self):
        self.generation += 1
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.hotkeys.close()
        self.tick_timer.stop()
        self.retry_timer.stop()
        if self.save_timer.isActive():
            self.save_timer.stop()
            self.save()
        self.tray.hide()
        for window in (self.lyric_window, self.card_window, self.settings_ui):
            window.hide()
        self.provider.stop()
        if self.provider.isRunning():
            self.provider.wait()
        self.log.close()
        logging.getLogger("spotiflying").removeHandler(self.log)


def instance(qt):
    name = "SpotiFlying-" + hashlib.sha256(os.environ.get("LOCALAPPDATA", str(Path.home())).encode()).hexdigest()[:16]
    client = QLocalSocket()
    client.connectToServer(name)
    if client.waitForConnected(350):
        client.disconnectFromServer()
        return None
    server = QLocalServer(qt)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    return server if server.listen(name) else None


def main():
    parser = argparse.ArgumentParser(prog="SpotiFlying")
    parser.add_argument("--demo", action="store_true", help="Executa a demonstração offline.")
    parser.add_argument("--tray", action="store_true", help="Inicia na bandeja.")
    for option in ("smoke", "capture", "probe"):
        parser.add_argument("--" + option, type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.smoke or options.capture:
        options.demo = True
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GuiPaicheco.SpotiFlying.Desktop")
    qt = QApplication([sys.argv[0]])
    qt.setApplicationName("SpotiFlying")
    qt.setApplicationVersion(__version__)
    qt.setQuitOnLastWindowClosed(False)
    isolated = next((path for path in (options.smoke, options.capture, options.probe) if path), None)
    server = instance(qt) if isolated is None else None
    if server is None and isolated is None:
        return 0
    controller = Controller(qt, options, None if isolated is None else isolated / "sandbox")
    if server:
        def reveal():
            while server.hasPendingConnections():
                connection = server.nextPendingConnection()
                connection.deleteLater()
            controller.open_settings()
        server.newConnection.connect(reveal)
    if isolated:
        from .verification import run_verification

        run_verification(controller, options)
    return qt.exec()
