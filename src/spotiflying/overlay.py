"""Independent transparent surfaces in Qt logical coordinates."""
import logging
import math
import re
from time import monotonic

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath
from PySide6.QtGui import QIcon, QKeySequence, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QSlider, QToolButton, QWidget

from .platform import overlay_styles

LOGGER = logging.getLogger(__name__)
LEFT = Qt.MouseButton.LeftButton


def geometry(area, size, placement, kind):
    width = min(area.width(), size.width())
    height = min(area.height(), size.height())
    if placement:
        anchor = placement["anchor"]
        if anchor == "br":
            x = area.x() + area.width() - width
            y = area.y() + area.height() - height
        elif anchor == "center":
            x = area.center().x() - width // 2
            y = area.center().y() - height // 2
        else:
            x, y = area.x(), area.y()
        x += placement["x"]
        y += placement["y"]
    elif kind == "lyrics":
        x, y = area.x() + round(area.width() * .09), area.y() + round(area.height() * .17)
    else:
        x, y = area.x() + area.width() - width - 24, area.y() + area.height() - height - 24
    return QRect(max(area.x(), min(x, area.x() + area.width() - width)),
                 max(area.y(), min(y, area.y() + area.height() - height)), width, height)


class Overlay(QWidget):
    cancel = Signal()
    activity = Signal()

    def __init__(self, kind):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        self.kind = kind
        self.state = "passive"
        self.topmost = True
        self.drag = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape.activated.connect(self.cancel)
        self.setWindowTitle("SpotiFlying · " + ("Letras" if kind == "lyrics" else "Cartão"))

    def mode(self, state, topmost):
        if self.state == state and self.topmost == topmost:
            return
        self.state, self.topmost = state, topmost
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, state == "passive")
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, state == "passive")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, topmost)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, state != "interactive")
        if visible:
            self.show()
        self.apply_native()
        self.update()

    def apply_native(self):
        if self.isVisible():
            try:
                overlay_styles(int(self.winId()), self.state == "passive", self.topmost)
            except OSError:
                LOGGER.exception("Falha nos estilos de sobreposição")

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange) and hasattr(self, "state"):
            self.apply_native()
        return result

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel.emit()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.activity.emit()
        if self.state == "edit" and event.button() == LEFT:
            point = event.position()
            scale = point.x() >= self.width() - 22 and point.y() >= self.height() - 22
            self.drag = (event.globalPosition().toPoint(), self.geometry(), scale)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.state == "interactive":
            self.activity.emit()
        if self.drag:
            start, rect, scale = self.drag
            delta = event.globalPosition().toPoint() - start
            if scale:
                self.resize(max(110, rect.width() + delta.x()), max(44, rect.height() + delta.y()))
            else:
                self.move(rect.topLeft() + delta)

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.activity.emit()

    def frame(self, painter):
        if self.state != "edit":
            return
        painter.setOpacity(1)
        painter.setPen(QPen(QColor("#5de3c9"), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
        painter.fillRect(self.width() - 16, self.height() - 16, 13, 13, QColor("#5de3c9"))


def emphasis_range(text, manual):
    if manual:
        match = re.search(re.escape(manual), text, re.I)
        return match.span() if match else (-1, -1)
    words = list(re.finditer(r"[^\W\d_][\w’'-]*", text, re.UNICODE))
    if not words:
        return -1, -1
    return max(words, key=lambda word: len(word[0])).span()


def font_for(visual, scale):
    font = QFont(visual["font"])
    font.setPixelSize(max(8, round(visual["size"] * scale)))
    font.setWeight(min(QFont.Weight, key=lambda weight: abs(weight.value - visual["weight"])))
    font.setItalic(visual["italic"])
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, visual["tracking"] * scale)
    return font


class LyricOverlay(Overlay):
    def __init__(self, visual):
        super().__init__("lyrics")
        self.visual = visual
        self.cues = []
        self.previous = []
        self.position = 0
        self.progress = 0
        self.changed = 0
        self.manual = ""
        self.reduced = False
        self.cache = {}
        self.tint = None

    def show_cues(self, cues, position, progress, jump, manual):
        motion_duration = self.visual["motion_ms"] / 1000
        changed = cues != self.cues or manual != self.manual
        if changed:
            self.previous = self.cues
            self.cues = cues
            self.changed = 0 if jump or not self.previous else monotonic()
            self.manual = manual
        animated = bool(self.changed and not self.reduced and monotonic() - self.changed <= motion_duration + .1)
        progressive = bool(cues and (self.visual["mode"] in ("Palavra", "Palavra estimada")
                                     or self.visual["phrase_progress"] or self.visual["scroll"]))
        if changed or animated or progressive or self.state == "edit":
            self.position = position
            self.progress = progress
            self.update()
        elif self.previous:
            self.previous = []
            self.update()

    def typeset(self, text, scale, active, width):
        visual = self.visual
        key = (text, scale, active, width, self.manual)
        if key in self.cache:
            return self.cache[key]
        emphatic = emphasis_range(text, self.manual) if active and visual["emphasis"] > 1 else (-1, -1)
        regular = font_for(visual, scale)
        larger = font_for(visual, scale * visual["emphasis"])
        metrics = {False: QFontMetricsF(regular), True: QFontMetricsF(larger)}
        space = metrics[False].horizontalAdvance(" ")
        rows = []
        for line in text.split("\n"):
            row = []
            x = 0.0
            words = list(re.finditer(r"\S+", line))
            for word in words:
                special = word.start() < emphatic[1] and word.end() > emphatic[0] and len(text.splitlines()) == 1
                value = word[0].upper() if visual["uppercase"] else word[0]
                measure = metrics[special]
                if measure.horizontalAdvance(value) > width:
                    value = measure.elidedText(value, Qt.TextElideMode.ElideRight, max(1, int(width)))
                advance = measure.horizontalAdvance(value)
                if row and x + advance > width:
                    if not visual["wrap"]:
                        offset, *_ = row[-1]
                        remaining = line[row[-1][-1]:]
                        if visual["uppercase"]:
                            remaining = remaining.upper()
                        clipped = metrics[False].elidedText(remaining, Qt.TextElideMode.ElideRight,
                                                           max(1, int(width - offset)))
                        row[-1] = (offset, clipped, regular, metrics[False], row[-1][-1])
                        break
                    rows.append(row)
                    row, x = [], 0.0
                row.append((x, value, larger if special else regular, measure, word.start()))
                x += advance + space
            if row:
                rows.append(row)
        result = []
        for row in rows:
            ascent = max(item[3].ascent() for item in row)
            descent = max(item[3].descent() for item in row)
            last = row[-1]
            row_width = last[0] + last[3].horizontalAdvance(last[1])
            paths = []
            for x, word, font, _, index in row:
                path = QPainterPath()
                path.addText(QPointF(x, ascent), font, word)
                paths.append((path, index))
            result.append((max(8, ascent + descent + visual["spacing"]), row_width, paths))
        if len(self.cache) >= 150:
            self.cache.clear()
        self.cache[key] = result
        return result

    def paint_cues(self, painter, cues, alpha, translation=0, scale=1):
        if not cues or alpha <= 0:
            return
        visual = self.visual
        padding = max(3, visual["padding"])
        width = max(10, self.width() - padding * 2)
        height = max(10, self.height() - padding * 2)
        base = min(1.0, max(.52, width / max(335, visual["size"] * 6)))
        rows = []
        for factor in (1, .88, .74, .6, .48):
            rows = [(row, cue, active) for cue, active in cues for row in self.typeset(
                cue.text, base * factor * visual["active_scale" if active else "context_scale"], active, width)]
            if sum(row[0] for row, _, _ in rows) <= height:
                break
        total = sum(row[0] for row, _, _ in rows)
        extra = max(0, height - total)
        if total > height and visual["scroll"]:
            extra = -(total - height) * self.progress
        elif visual["y_align"] == "Centro":
            extra /= 2
        elif visual["y_align"] == "Topo":
            extra = 0
        painter.save()
        painter.translate(0, translation + extra)
        painter.scale(scale, scale)
        y = padding
        for (row_height, row_width, paths), cue, active in rows:
            if y > height + padding:
                break
            x = padding
            if visual["x_align"] == "Centro":
                x += (width - row_width) / 2
            elif visual["x_align"] == "Direita":
                x += width - row_width
            painter.save()
            painter.translate(x, y)
            painter.setOpacity(alpha * (1 if active else .68) * visual["opacity"] / 100)
            for path, index in paths:
                color = self.tint if active and visual["art_tint"] and self.tint else QColor(
                    visual["color"] if active else visual["secondary"])
                if active and visual["mode"] == "Palavra":
                    stamp = next((stamp for stamp, start in reversed(cue.words) if start <= index), None)
                    if stamp is not None and stamp > self.position:
                        color = QColor(visual["secondary"])
                elif active and visual["mode"] == "Palavra estimada" and index > self.progress * len(cue.text):
                    color = QColor(visual["secondary"])
                if visual["shadow"]:
                    painter.fillPath(path.translated(0, 2), QColor(0, 0, 0, 134))
                if visual["outline"]:
                    painter.strokePath(path, QPen(QColor("#202624"), visual["outline"]))
                if visual["gradient"] and active:
                    gradient = QLinearGradient(0, 0, 0, row_height)
                    gradient.setColorAt(0, color)
                    gradient.setColorAt(1, QColor(visual["secondary"]))
                    painter.fillPath(path, gradient)
                else:
                    painter.fillPath(path, color)
            painter.restore()
            y += row_height
        painter.restore()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        visual = self.visual
        if self.state == "edit":
            painter.fillRect(self.rect(), QColor(18, 31, 28, 125))
        if visual["background_alpha"]:
            background = QColor(visual["background"])
            background.setAlphaF(visual["background_alpha"] * visual["opacity"] / 10000)
            painter.setBrush(background)
            painter.setPen(QPen(QColor("#54847b"), visual["border"]) if visual["border"] else Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(self.rect().adjusted(1, 1, -1, -1)), 12, 12)
        duration = visual["motion_ms"] / 1000
        progress = min(1.0, (monotonic() - self.changed) / duration) if duration and not self.reduced else 1
        style = visual["animation"]
        if visual["easing"] == "Suave":
            progress = 1 - (1 - progress) ** 3
        shift = visual["intensity"]
        alpha = progress if style in ("Fade", "Fade e slide") else 1
        slide = (1 - progress) * shift if style in ("Slide", "Fade e slide") else 0
        scale = 1 - (1 - progress) * shift / 100 if style == "Escala" else 1
        if style == "Bounce":
            slide = math.sin(progress * math.pi) * -shift
        if progress < 1 and style in ("Fade", "Fade e slide"):
            self.paint_cues(painter, self.previous, 1 - progress, -shift * progress if slide else 0)
        if style == "Revelação":
            painter.save()
            painter.setClipRect(0, 0, round(self.width() * progress), self.height())
        self.paint_cues(painter, self.cues, alpha, slide, scale)
        if style == "Revelação":
            painter.restore()
        if visual["phrase_progress"] and self.cues:
            painter.fillRect(3, self.height() - 4, round((self.width() - 6) * self.progress), 2, QColor("#64dfc8"))
        self.frame(painter)


def time_label(ms):
    seconds = max(0, int(ms or 0) // 1000)
    return f"{seconds // 60}:{seconds % 60:02}"


class CardOverlay(Overlay):
    command = Signal(str, object)
    BUTTONS = {"previous": "‹‹", "play": "▶", "next": "››", "shuffle": "⇄", "repeat": "↻"}

    def __init__(self, visual, icon):
        super().__init__("card")
        self.visual = visual
        self.neutral = QIcon(icon).pixmap(256, 256)
        self.cover = QPixmap()
        self.snapshot = None
        self.position = None
        self.paint_key = None
        self.next_line = ""
        self.source = ""
        self.buttons = {}
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setAccessibleName("Posição na faixa")
        self.slider.sliderReleased.connect(self.seek)
        self.slider.setStyleSheet("QSlider::groove:horizontal { background:#34534d; height:4px; }"
                                  "QSlider::handle:horizontal { background:#64dfc8; width:10px; margin:-3px 0; }")
        self.interactive = QLabel("INTERATIVO  ·  Esc encerra", self)
        self.interactive.setStyleSheet("color:#77e4d0; font:600 10px 'Segoe UI'; background:transparent;")
        for name, mark in self.BUTTONS.items():
            button = QToolButton(self)
            button.setText(mark)
            button.setAccessibleName({"play": "Reproduzir ou pausar", "previous": "Faixa anterior",
                                      "next": "Próxima faixa", "shuffle": "Aleatório", "repeat": "Repetição"}[name])
            button.setStyleSheet("QToolButton { background:#29433f;color:white;border:1px solid #3c655e;"
                                 "border-radius:5px;font-size:14px; } QToolButton:disabled {color:#78908b;}"
                                 "QToolButton:focus {border-color:#7ce4d1;}")
            button.clicked.connect(lambda checked=False, name=name: self.send(name))
            self.buttons[name] = button
        self.update_data(None, None, "", "", True)

    def seek(self):
        self.activity.emit()
        self.command.emit("seek", self.slider.value())

    def send(self, name):
        self.activity.emit()
        if not self.snapshot:
            return
        value = None
        if name == "play" and self.snapshot.timeline.playing:
            name = "pause"
        elif name in ("shuffle", "repeat"):
            value = not getattr(self.snapshot, name)
        self.command.emit(name, value)

    def mode(self, state, topmost):
        super().mode(state, topmost)
        self.layout_controls()

    def update_data(self, snapshot, position, next_line, source, reload_cover=False):
        self.snapshot, self.position, self.next_line, self.source = snapshot, position, next_line, source
        if reload_cover:
            self.cover = QPixmap()
            if snapshot and snapshot.artwork:
                self.cover.loadFromData(snapshot.artwork)
        selected = self.visual["card_items"]
        track = snapshot.track if snapshot else None
        state = snapshot.state if snapshot else ""
        playhead = None
        if self.state == "interactive" or "Progresso" in selected:
            playhead = round((position or 0) / 100)
        elif "Tempo atual" in selected or "Tempo restante" in selected:
            playhead = int((position or 0) / 1000)
        key = (track, state, playhead, self.state, next_line if "Próxima linha" in selected else "",
               source if "Fonte" in selected else "",
               snapshot.capabilities if snapshot else (),
               snapshot.shuffle if snapshot else False, snapshot.repeat if snapshot else False)
        if key == self.paint_key and not reload_cover:
            return
        self.paint_key = key
        self.layout_controls()
        self.update()

    def layout_controls(self):
        interactive = self.state == "interactive"
        show_controls = interactive and self.visual["card_interactive_controls"]
        explicit = self.state == "passive" and "Controles" in self.visual["card_items"]
        self.interactive.setVisible(interactive)
        self.interactive.setGeometry(9, max(0, self.height() - (72 if show_controls else 22)), self.width() - 18, 12)
        controls = self.snapshot.capabilities if self.snapshot and interactive else ()
        width = max(19, (self.width() - 29) // 5)
        for i, (name, button) in enumerate(self.buttons.items()):
            actual = "pause" if name == "play" and self.snapshot and self.snapshot.timeline.playing else name
            button.setVisible(show_controls or explicit)
            button.setGeometry(8 + i * (width + 3), self.height() - 29, width, 22)
            button.setEnabled(actual in controls)
            button.setToolTip(button.accessibleName() if actual in controls else "Comando indisponível nesta sessão")
            if name == "play":
                button.setText("Ⅱ" if actual == "pause" else "▶")
        self.slider.setVisible(show_controls)
        self.slider.setGeometry(8, self.height() - 57, self.width() - 16, 20)
        duration = self.snapshot.timeline.duration if self.snapshot else 0
        self.slider.setRange(0, duration)
        if not self.slider.isSliderDown():
            self.slider.setValue(round(self.position or 0))
        self.slider.setEnabled(bool(duration and "seek" in controls))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_controls()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        visual = self.visual
        painter.setOpacity(visual["card_opacity"] / 100)
        bounds = QRectF(self.rect().adjusted(1, 1, -1, -1))
        radius = visual["card_radius"]
        if visual["card_shadow"]:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 95))
            painter.drawRoundedRect(bounds.translated(0, 1), radius, radius)
        painter.setPen(QPen(QColor("#68d9c3" if self.state == "interactive" else "#41645d"), visual["card_border"])
                       if visual["card_border"] else Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#182725"))
        painter.drawRoundedRect(bounds, radius, radius)
        snap = self.snapshot
        duration = snap.timeline.duration if snap else 0
        items = {
            "Título": snap.track.title if snap else "Abra o Spotify",
            "Artista": snap.track.artist if snap else "e coloque uma música",
            "Álbum": snap.track.album if snap else "",
            "Tempo atual": time_label(self.position), "Tempo restante": "−" + time_label(duration - (self.position or 0)),
            "Duração": time_label(duration), "Fonte": self.source, "Estado": {
                "PLAYING": "Reproduzindo", "PAUSED": "Pausado",
            }.get(snap.state, snap.state) if snap else "Sem sessão", "Próxima linha": self.next_line,
        }
        padding, spacing = visual["card_padding"], visual["card_spacing"]
        selected = set(visual["card_items"])
        ordered = [item for item in visual["item_order"] if item in selected and item != "Controles"]
        controls = (74 if visual["card_interactive_controls"] else 24) if self.state == "interactive" else (
            29 if "Controles" in selected else 0)
        content_h = self.height() - controls
        x, y = padding, padding
        painter.setClipRect(1, 1, self.width() - 2, max(1, content_h - 2))
        vertical = visual["card_layout"] == "Vertical"
        groups = []
        for item in ordered:
            if item in ("Capa", "Ícone"):
                groups.append(item)
            elif item == "Progresso" or items.get(item):
                if not groups or isinstance(groups[-1], str):
                    groups.append([])
                groups[-1].append((item, items.get(item, "")))
        sides = sum(isinstance(group, str) for group in groups)
        columns = len(groups) - sides
        usable_width = max(1, self.width() - padding * 2)
        cover = min(visual["cover"], max(12, content_h - padding * 2), usable_width)
        if not vertical and sides and columns:
            cover = min(cover, max(12, (usable_width - columns * 48) // sides))
        text_width = max(1, (usable_width - sides * cover - max(0, len(groups) - 1) * spacing)
                         // max(1, columns)) if not vertical else usable_width
        for group in groups:
            if isinstance(group, str):
                art = self.cover if group == "Capa" and not self.cover.isNull() else self.neutral
                art_x = x
                if vertical and visual["card_align"] == "Centro":
                    art_x = (self.width() - cover) // 2
                elif vertical and visual["card_align"] == "Direita":
                    art_x = self.width() - cover - padding
                target = QRect(art_x, y if vertical else max(y, (content_h - cover) // 2), cover, cover)
                painter.save()
                clip = QPainterPath()
                clip.addRoundedRect(QRectF(target), 6, 6)
                painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                painter.drawPixmap(target, art)
                painter.restore()
                if vertical:
                    y += cover + spacing
                else:
                    x += cover + spacing
            else:
                text_y = y if vertical else max(y, (content_h - len(group) * 16) // 2)
                self.draw_text_group(painter, group, x, text_y, text_width, content_h, duration)
                if vertical:
                    y += len(group) * 16 + spacing
                else:
                    x += text_width + spacing
        painter.setClipping(False)
        self.frame(painter)

    def draw_text_group(self, painter, pending, x, y, available, content_h, duration):
        visual = self.visual
        for item, label in pending:
            if y + 11 > content_h:
                break
            if item == "Progresso":
                painter.fillRect(x, y + 6, available, 3, QColor("#41645d"))
                if duration and self.position:
                    painter.fillRect(x, y + 6, round(available * min(1, self.position / duration)), 3, QColor("#64dfc8"))
            else:
                font = QFont("Segoe UI")
                font.setPixelSize(13 if item == "Título" else 11)
                font.setBold(item == "Título")
                painter.setFont(font)
                painter.setPen(QColor("#f1fffc" if item == "Título" else "#b4cfca"))
                align = {"Esquerda": Qt.AlignmentFlag.AlignLeft, "Centro": Qt.AlignmentFlag.AlignHCenter,
                         "Direita": Qt.AlignmentFlag.AlignRight}[visual["card_align"]]
                clipped = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, available)
                painter.drawText(x, y, available, 16, align | Qt.AlignmentFlag.AlignVCenter, clipped)
            y += 16


def active_screen():
    return QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
