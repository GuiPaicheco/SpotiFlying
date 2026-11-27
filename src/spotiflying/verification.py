"""Executable smoke and capture scenarios using only fictitious demo tracks."""
import json
import platform

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from .platform import WINDOWS


class Backdrop(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.light = False

    def paintEvent(self, _):
        paint = QPainter(self)
        paint.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QLinearGradient(0, 0, self.width(), self.height())
        palette = ("#b5c8ba", "#d5cabb", "#8bb7a6") if self.light else ("#101c24", "#1e3938", "#355d50")
        for stop, value in zip((0, .55, 1), palette):
            color.setColorAt(stop, QColor(value))
        paint.fillRect(self.rect(), color)
        w, h = self.width(), self.height()
        paint.setPen(Qt.PenStyle.NoPen)
        paint.setBrush(QColor("#ffffff" if self.light else "#8ed0bc"))
        paint.setOpacity(.1)
        for i in range(7):
            paint.drawEllipse(w // 2 + i * w // 18, h // 5 + i * h // 22,
                              w // 2 + i * w // 20, h * 2 // 3)


def run_verification(app, options):
    directory = options.smoke or options.capture or options.probe

    def finish(report):
        common = {"platform": platform.version(), "scale": app.qt.primaryScreen().devicePixelRatio()}
        path = directory / ("probe.json" if options.probe else "smoke.json")
        path.write_text(json.dumps({**common, **report}, indent=2) + "\n", encoding="utf-8")
        app.qt.exit(0 if report["ok"] else 1)

    def probe():
        snapshot = app.snapshot
        finish({"ok": bool(snapshot), "spotify_session": bool(snapshot),
                "source_application": snapshot.session_id if snapshot else "",
                "position": bool(snapshot and snapshot.timeline.position is not None),
                "duration": bool(snapshot and snapshot.timeline.duration),
                "art": bool(snapshot and snapshot.artwork),
                "state": snapshot.state if snapshot else "", "provider_status": app.provider_status})

    def smoke():
        import ssl

        from .platform import user32

        glyph = app.lyric_window.grab().toImage()
        card = app.card_window.grab().toImage()
        passive = []
        for window in (app.lyric_window, app.card_window):
            flags = user32.GetWindowLongPtrW(int(window.winId()), -20) if WINDOWS else 0
            passive.append(flags & 0x080800a0 == 0x080800a0)
        app.command("pause")
        frozen = app.playhead.position()
        app.command("seek", 7100)
        seek = app.playhead.position() == 7100 and app.last_index == 1
        app.command("next")
        switched = app.snapshot.track.title == "Tempo de Vidro" and not app.lyric_window.cues
        app.toggle_interaction()
        mode = app.card_window.state == "interactive" and app.lyric_window.state == "passive"
        app.cancel_mode()
        qt_image = glyph.pixelColor(0, 0).alpha() == 0 and card.pixelColor(16, 16).alpha() > 0
        try:
            ssl.create_default_context()
            catalog_tls = True
        except (OSError, ValueError):
            catalog_tls = False
        checks = {"catalog_tls": catalog_tls,
                  "transparent_background": qt_image, "passive_hwnd_styles": all(passive),
                  "pause": frozen is not None, "seek": seek, "new_track": switched,
                  "interaction_isolated": mode, "escape_handler": app.card_window.state == "passive",
                  "tray_visible": app.tray.isVisible()}
        finish({"ok": all(checks.values()), **checks})

    def capture():
        screen = app.qt.primaryScreen()
        rect = screen.availableGeometry()
        background = Backdrop()
        background.setGeometry(rect)
        background.show()
        background.raise_()
        app.restore_reference()
        app.demo_playing = False
        app.demo_snapshot(1100, True)
        app.lyric_window.raise_()
        app.card_window.raise_()

        saved = set()

        def captured(name, crop=None):
            desktop = screen.grabWindow(0, rect.x() - screen.geometry().x(), rect.y() - screen.geometry().y(),
                                        rect.width(), rect.height())
            reference = background.grab().toImage()
            observed = desktop.toImage()
            if desktop.isNull() or observed.size() != reference.size():
                return
            w, h = observed.width(), observed.height()
            samples = [(int(w * x / 20), int(h * y / 12)) for x in range(20) for y in range(12)]
            scale = desktop.devicePixelRatio()
            windows = [QRect(*(round(value * scale) for value in (
                win.x() - rect.x(), win.y() - rect.y(), win.width(), win.height())))
                for win in (app.lyric_window, app.card_window)]
            for x, y in samples:
                if any(window.contains(x, y) for window in windows):
                    continue
                actual, expected = observed.pixelColor(x, y), reference.pixelColor(x, y)
                if sum(abs(a - b) for a, b in zip(actual.getRgb()[:3], expected.getRgb()[:3])) > 14:
                    return
            if crop:
                region = QRect(*(round(value * scale) for value in (crop.x(), crop.y(), crop.width(), crop.height())))
                desktop = desktop.copy(region)
            if desktop.save(str(directory / name)):
                saved.add(name)

        def settings():
            app.cancel_mode()
            app.change("lyrics_visible", False, False)
            app.change("card_visible", False, False)
            app.change("theme", "Escuro", False)
            app.open_settings("Aparência")
            app.settings_ui.move(rect.center() - app.settings_ui.rect().center())
            QTimer.singleShot(400, done)

        def done():
            if app.settings_ui.grab().save(str(directory / "central.png")):
                saved.add("central.png")
            background.close()
            finish({"ok": len(saved) == 4, "captures": sorted(saved)})

        def player():
            app.toggle_interaction()
            QTimer.singleShot(350, snap_player)

        def snap_player():
            pos = app.card_window.geometry().translated(-rect.topLeft()).adjusted(-22, -22, 22, 22)
            captured("miniplayer.png", pos)
            settings()

        def light():
            captured("stories-claro.png")
            background.light = False
            background.update()
            player()

        def dark():
            captured("stories.png")
            background.light = True
            background.update()
            QTimer.singleShot(350, light)

        if rect.width() < 600 or rect.height() < 400:
            finish({"ok": False, "reason": "no usable display"})
        else:
            QTimer.singleShot(500, dark)
            QTimer.singleShot(25000, lambda: finish({"ok": False, "reason": "capture timeout",
                                                    "captures": sorted(saved)}))

    if options.probe:
        QTimer.singleShot(7000, probe)
    elif options.capture:
        capture()
    else:
        QTimer.singleShot(700, smoke)
