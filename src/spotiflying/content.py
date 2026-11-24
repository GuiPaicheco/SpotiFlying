"""Track lifecycle, lyric requests and lyric controls."""
from dataclasses import replace
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from .demo import DEMO
from .lyrics import CatalogError, Cue, Lyrics, from_catalog, parse
from .playback import Snapshot
from .sync import Timeline

STATUS = {
    "loading": "Buscando a letra…", "sync": "Letra sincronizada", "static": "Letra estática",
    "instrumental": "Faixa instrumental", "missing": "Letra indisponível", "error": "Tente novamente em instantes",
}


class Content:
    def spotify_snapshot(self, snapshot):
        self.last_spotify = snapshot
        if not self.demo:
            self.receive_snapshot(snapshot)

    def receive_snapshot(self, snapshot, force=False):
        old = self.snapshot
        changed = (old.track.identity if old else None) != (snapshot.track.identity if snapshot else None)
        artwork_changed = changed or (old.artwork if old else b"") != (snapshot.artwork if snapshot else b"")
        self.snapshot = snapshot
        timeline = snapshot.timeline if snapshot else Timeline()
        if snapshot and snapshot.reference and timeline.playing and timeline.position is not None:
            age = max(0, monotonic() - snapshot.reference)
            timeline = replace(timeline, position=timeline.position + min(2, age) * timeline.rate * 1000)
        self.jump |= self.playhead.update(timeline, force or changed or bool(snapshot and snapshot.discontinuity))
        if changed or (old and snapshot and old.track.key != snapshot.track.key):
            self.reload_lyrics(not changed)
        if artwork_changed:
            self.card_window.update_data(snapshot, self.playhead.position(), "", "", True)
            cover = self.card_window.cover
            self.lyric_window.tint = None if cover.isNull() else QColor(
                cover.scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation).toImage()
                .pixelColor(0, 0)).lighter(165)
        if changed and snapshot and not self.demo and self.data["history_enabled"]:
            self.data["history"] = [f"{snapshot.track.title} · {snapshot.track.artist}", *self.data["history"]][:100]
            self.save_later()
        self.tick()

    def set_demo(self, enabled):
        if self.demo == enabled:
            return
        self.demo = enabled
        if enabled:
            self.demo_index = 0
            self.demo_playing = True
            self.demo_snapshot(0, True)
        else:
            if not self.provider.isRunning() and not self.options.smoke:
                self.provider.start()
            self.receive_snapshot(self.last_spotify, True)
        self.sync_ui()

    def demo_snapshot(self, position, force=False):
        track, _ = DEMO[self.demo_index]
        playing = self.demo_playing
        self.receive_snapshot(Snapshot(
            "demo", track, Timeline(position, track.duration, playing), "PLAYING" if playing else "PAUSED",
            frozenset(("play", "pause", "next", "previous", "seek", "shuffle", "repeat")),
            shuffle=self.demo_shuffle, repeat=self.demo_repeat,
        ), force)

    def command(self, name, value=None):
        if not self.snapshot:
            self.notify("Abra o Spotify e coloque uma música.")
            return
        if name == "toggle":
            name = "pause" if self.snapshot.timeline.playing else "play"
        if not self.demo:
            self.provider.command(name, value)
            return
        position = self.playhead.position() or 0
        if name in ("play", "pause"):
            self.demo_playing = name == "play"
        elif name == "seek":
            position = value
        elif name == "repeat":
            self.demo_repeat = bool(value)
        elif name == "shuffle":
            self.demo_shuffle = bool(value)
        elif name in ("next", "previous"):
            step = 2 if self.demo_shuffle else 1
            self.demo_index = (self.demo_index + (step if name == "next" else -step)) % len(DEMO)
            position = 0
        self.demo_snapshot(position, name in ("seek", "next", "previous"))

    def reload_lyrics(self, preserve=False):
        self.generation += 1
        generation = self.generation
        self.candidates = []
        self.error = ""
        track = self.snapshot.track if self.snapshot else None
        if not preserve:
            self.lyrics = Lyrics("missing")
            self.lyric_window.show_cues([], 0, 0, True, "")
        if not track:
            self.update_preview()
            return
        if self.demo:
            self.lyrics = DEMO[self.demo_index][1]
            return
        association = self.data["associations"].get(track.key) or self.data["associations"].get(track.identity)
        if association:
            try:
                path = Path(association)
                if path.suffix.lower() not in (".lrc", ".txt") or path.stat().st_size > 2_000_000:
                    raise ValueError("invalid lyric file")
                self.lyrics = parse(path.read_text(encoding="utf-8-sig"), "Arquivo local", path.suffix.lower() == ".lrc")
                self.update_preview()
                return
            except (OSError, ValueError):
                self.error = "Arquivo de letra inacessível ou com codificação inválida."
        if not self.data["catalog"] or not track.artist:
            self.update_preview()
            return
        cached = self.choices.get(track.key) or self.cache.get(track.key)
        if cached and cached[0] > monotonic():
            self.lyrics, self.candidates = cached[1:]
            self.update_preview()
            return
        if self.lyrics.status not in ("sync", "static", "instrumental"):
            self.lyrics = Lyrics("loading")
        self.executor.submit(self.lookup, track, generation)

    def lookup(self, track, generation):
        if generation != self.generation:
            return
        try:
            lyrics, candidates = self.catalog.lookup(track, lambda: generation != self.generation)
            if generation == self.generation:
                self.fetched.emit(generation, lyrics, candidates, "")
        except CatalogError as error:
            if generation == self.generation:
                self.fetched.emit(generation, Lyrics("error"), [], str(error))

    def receive_lyrics(self, generation, lyrics, candidates, error):
        if generation != self.generation or not self.snapshot:
            return
        if not error or self.lyrics.status not in ("sync", "static", "instrumental"):
            self.lyrics = lyrics
        self.candidates = candidates
        self.error = error
        self.jump = True
        if not error:
            self.remember(self.cache, self.snapshot.track.key, lyrics, candidates)
        else:
            self.retry_timer.start(max(1000, round((self.catalog.retry_at - monotonic()) * 1000)))
        self.tick()

    @staticmethod
    def remember(cache, key, lyrics, candidates):
        cache[key] = (monotonic() + 1800, lyrics, candidates)
        cache.move_to_end(key)
        while len(cache) > 20:
            cache.popitem(last=False)

    def choose_candidate(self):
        if not self.candidates or not self.snapshot:
            self.notify("Nenhuma versão alternativa disponível.")
            return
        rows = self.candidates[:]
        key = self.snapshot.track.key
        labels = [f"{i + 1}. {row.get('trackName') or '?'} · {row.get('artistName') or '?'} · "
                  f"{row.get('albumName') or '?'} · {row.get('duration') or '?'} s" for i, row in enumerate(rows)]
        label, ok = QInputDialog.getItem(self.settings_ui, "Versão da letra", "Resultados LRCLIB", labels, 0, False)
        if not ok or not self.snapshot or self.snapshot.track.key != key:
            return
        selected = from_catalog(rows[labels.index(label)])
        remember = QMessageBox.question(self.settings_ui, "Memorizar versão",
                                        "Memorizar esta associação durante a sessão?") == QMessageBox.StandardButton.Yes
        if self.snapshot and self.snapshot.track.key == key:
            if remember:
                self.remember(self.choices, key, selected, rows)
            self.lyrics = selected
            self.jump = True
            self.tick()

    def import_lyrics(self):
        if not self.snapshot or self.demo:
            self.notify("Selecione uma faixa do Spotify para vincular um arquivo.")
            return
        key = self.snapshot.track.key
        name, _ = QFileDialog.getOpenFileName(self.settings_ui, "Vincular letra", "", "Letras (*.lrc *.txt)")
        if not name:
            return
        path = Path(name)
        try:
            if path.suffix.lower() not in (".lrc", ".txt") or path.stat().st_size > 2_000_000:
                raise ValueError("invalid lyric file")
            path.read_text(encoding="utf-8-sig")
        except (OSError, ValueError):
            self.notify("Selecione um arquivo .lrc ou .txt em UTF-8 de até 2 MB.")
            return
        self.data["associations"][key] = str(path.resolve())
        self.save_later()
        self.reload_lyrics()

    def unlink_lyrics(self):
        if self.snapshot:
            for key in (self.snapshot.track.key, self.snapshot.track.identity):
                self.data["associations"].pop(key, None)
            self.save_later()
            self.reload_lyrics()

    def nudge(self, amount):
        self.change("offset", max(-5000, min(5000, self.data["offset"] + amount)), False)
        self.jump = True

    def track_adjustment(self):
        if not self.snapshot:
            self.notify("Coloque uma faixa para editar o ajuste.")
            return
        key = self.snapshot.track.key
        offset, ok = QInputDialog.getInt(self.settings_ui, "Ajuste por faixa",
                                         "Ajuste em ms (+ adianta a letra)", self.data["track_offsets"].get(key, 0),
                                         -5000, 5000, 50)
        if ok:
            self.data["track_offsets"][key] = offset
            self.jump = True
            self.save_later()

    def edit_emphasis(self):
        if not self.snapshot:
            self.notify("Coloque uma faixa para editar a ênfase.")
            return
        key = self.snapshot.track.key
        value, ok = QInputDialog.getText(self.settings_ui, "Ênfase por faixa", "Palavra ou grupo a enfatizar",
                                         text=self.data["emphases"].get(key, ""))
        if ok:
            self.data["emphases"][key] = value.strip()[:256]
            self.save_later()

    def paint_position(self, position, duration, playing, interrupted):
        cues, following, active_text = [], "", ""
        visual = self.data["visual"]
        key = self.snapshot.track.key if self.snapshot else ""
        adjustment = self.data["offset"] + self.data["track_offsets"].get(key, 0)
        index = self.lyrics.index(position, adjustment) if position is not None else -1
        corrected = (position or 0) + adjustment + self.lyrics.offset
        progress = 0
        timed = self.lyrics.cues
        if position is not None and duration and position >= duration:
            pass
        elif self.lyrics.status == "static" or (self.lyrics.status == "sync" and position is None):
            cues = [(Cue(0, self.lyrics.text), True)]
        elif self.lyrics.status == "sync" and index >= 0 and timed[index].text:
            active_text = timed[index].text
            count = visual["lines"]
            start = index // count * count if visual["mode"] == "Página" else max(
                0, index - min(visual["previous"], count - 1))
            cues = [(timed[i], i == index) for i in range(start, min(len(timed), start + count)) if timed[i].text]
            if index + 1 < len(timed):
                following = timed[index + 1].text
            end = timed[index + 1].at if index + 1 < len(timed) else duration
            if end > timed[index].at:
                progress = max(0, min(1, (corrected - timed[index].at) / (end - timed[index].at)))
        self.lyric_window.reduced = self.data["reduced_motion"] or self.data["economy"] or not playing
        jump = self.jump or interrupted or abs(index - self.last_index) > 1
        if self.lyric_window.isVisible():
            self.lyric_window.show_cues(cues, corrected, progress, jump, self.data["emphases"].get(key, ""))
        self.jump = False
        self.last_index = index
        if self.card_window.isVisible():
            self.card_window.update_data(self.snapshot, position, following, self.lyrics.source)
        if self.settings_ui.isVisible():
            self.update_preview(active_text)

    def set_provider_status(self, status):
        self.provider_status = status
        self.update_preview()

    def update_preview(self, cue=""):
        if self.snapshot:
            status = "Escolha uma versão em Letras" if self.candidates else STATUS[self.lyrics.status]
            text = f"{self.snapshot.track.title} · {self.snapshot.track.artist}\n{status}"
            if self.lyrics.source:
                text += f" · {self.lyrics.source}"
            if self.snapshot.timeline.position is None and self.lyrics.status == "sync":
                text += "\nPosição indisponível. Exibindo texto estático."
            if self.error:
                text += f"\n{self.error}"
        else:
            text = self.provider_status or "Abra o Spotify e coloque uma música."
        self.settings_ui.show_preview(text, self.lyrics.text, cue)

    def clear_cache(self):
        self.generation += 1
        self.retry_timer.stop()
        self.cache.clear()
        self.choices.clear()
        self.candidates.clear()
        self.error = ""
        if self.lyrics.source == "LRCLIB" or self.lyrics.status == "loading":
            self.lyrics = Lyrics("missing")
        self.tick()
