"""Desktop playback via Windows' global media sessions."""
import asyncio
import logging
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Empty, SimpleQueue
from time import monotonic

from PySide6.QtCore import QThread, Signal

from .lyrics import track_key
from .sync import Timeline

LOGGER = logging.getLogger(__name__)
SPOTIFY_IDS = {"spotify.exe", "spotify", "spotifyab.spotifymusic_zpdnekdrzrea0!spotify",
               "spotifyab.spotifymusic_zpdnekdrzrea0!app"}
COMMANDS = {
    "play": ("is_play_enabled", "try_play_async"),
    "pause": ("is_pause_enabled", "try_pause_async"),
    "previous": ("is_previous_enabled", "try_skip_previous_async"),
    "next": ("is_next_enabled", "try_skip_next_async"),
    "seek": ("is_playback_position_enabled", "try_change_playback_position_async"),
    "shuffle": ("is_shuffle_enabled", "try_change_shuffle_active_async"),
    "repeat": ("is_repeat_enabled", "try_change_auto_repeat_mode_async"),
}


@dataclass(frozen=True)
class Track:
    title: str
    artist: str = ""
    album: str = ""
    duration: int = 0

    @property
    def key(self):
        return track_key(self.title, self.artist, self.album, self.duration)

    @property
    def identity(self):
        return track_key(self.title, self.artist, self.album, 0)


@dataclass(frozen=True)
class Snapshot:
    session_id: str
    track: Track
    timeline: Timeline
    state: str
    capabilities: frozenset[str] = frozenset()
    artwork: bytes = b""
    shuffle: bool = False
    repeat: bool = False
    discontinuity: bool = False
    reference: float = 0.0


def relative_timeline(info, properties, now):
    if not properties:
        return Timeline()
    start = properties.start_time.total_seconds()
    end = properties.end_time.total_seconds()
    raw_position = properties.position.total_seconds() - start
    duration = round(max(0, end - start) * 1000)
    state = info.playback_status.name if info else ""
    rate = info.playback_rate if info else None
    rate = rate if rate is not None and math.isfinite(rate) and 0 < rate <= 8 else 1.0
    playing = state == "PLAYING"
    updated = properties.last_updated_time
    age = (now - updated).total_seconds() if updated else -1
    if (not 0 <= raw_position <= 86400 or not 0 <= duration <= 86400000
            or duration and raw_position * 1000 > duration + 2000 or age < -1):
        return Timeline(None, duration, playing, rate)
    if not duration and not raw_position and not 0 <= age <= 30:
        return Timeline(None, duration, playing, rate)
    max_age = max(30, duration / 1000 + 5)
    if playing and 0 < age <= max_age:
        raw_position += age * rate
    position = min(raw_position * 1000, duration) if duration else raw_position * 1000
    return Timeline(position, duration, playing, rate)


class PlaybackProvider(QThread):
    snapshot = Signal(object)
    status = Signal(str)
    command_failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.commands = SimpleQueue()
        self.visible = True
        self.loop = None
        self.changed = None
        self.metadata_dirty = True

    def command(self, name, value=None):
        self.commands.put((name, value))
        self.wake()

    def wake(self, *_):
        if self.loop and self.changed:
            try:
                self.loop.call_soon_threadsafe(self.changed.set)
            except RuntimeError:
                pass

    def stop(self):
        self.requestInterruption()
        self.wake()

    def run(self):
        if sys.platform != "win32":
            self.status.emit("A reprodução local requer Windows.")
            return
        try:
            asyncio.run(self.watch())
        except ImportError:
            LOGGER.exception("Binding de mídia ausente")
            self.status.emit("Integração de mídia indisponível.")
        finally:
            self.loop = self.changed = None

    def metadata_event(self, *_):
        self.metadata_dirty = True
        self.wake()

    @staticmethod
    async def artwork(properties):
        from winrt.windows.storage.streams import DataReader

        if not properties.thumbnail:
            return b""
        stream = await properties.thumbnail.open_read_async()
        try:
            if not 0 < stream.size <= 4_000_000:
                return b""
            reader = DataReader(stream)
            try:
                await reader.load_async(stream.size)
                buffer = bytearray(stream.size)
                reader.read_bytes(buffer)
                return bytes(buffer)
            finally:
                reader.close()
        finally:
            stream.close()

    async def execute(self, session, capabilities, name, value):
        if name not in capabilities:
            self.command_failed.emit("O Spotify não disponibilizou este comando.")
            return
        try:
            method = getattr(session, COMMANDS[name][1])
            arguments = ()
            if name == "seek":
                arguments = (int(value * 10000),)
            elif name == "shuffle":
                arguments = (bool(value),)
            elif name == "repeat":
                from winrt.windows.media import MediaPlaybackAutoRepeatMode
                arguments = (MediaPlaybackAutoRepeatMode.LIST if value else MediaPlaybackAutoRepeatMode.NONE,)
            if not await asyncio.wait_for(method(*arguments), 3):
                self.command_failed.emit("O Spotify recusou o comando.")
        except (OSError, RuntimeError, TimeoutError):
            self.command_failed.emit("O Spotify não respondeu ao comando.")

    async def watch(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

        self.loop = asyncio.get_running_loop()
        self.changed = asyncio.Event()
        session = manager = None
        manager_token = None
        subscriptions = []
        identity = ""
        track = Track("")
        cover = b""
        previous = None
        last_poll = monotonic()
        capabilities = frozenset()
        while not self.isInterruptionRequested():
            self.changed.clear()
            try:
                if manager is None:
                    manager = await asyncio.wait_for(GlobalSystemMediaTransportControlsSessionManager.request_async(), 4)
                    manager_token = manager.add_sessions_changed(self.wake)
                sessions = [item for item in manager.get_sessions()
                            if item.source_app_user_model_id.casefold() in SPOTIFY_IDS]
                available = next((item for item in sessions if item.source_app_user_model_id == identity),
                                 sessions[0] if sessions else None)
                if available != session:
                    for remove, token in subscriptions:
                        remove(token)
                    subscriptions.clear()
                    session = available
                    track = Track("")
                    cover = b""
                    self.metadata_dirty = True
                    if session:
                        identity = session.source_app_user_model_id
                        for event, callback in (("media_properties_changed", self.metadata_event),
                                                ("playback_info_changed", self.wake),
                                                ("timeline_properties_changed", self.wake)):
                            token = getattr(session, "add_" + event)(callback)
                            subscriptions.append((getattr(session, "remove_" + event), token))
                if session:
                    info = session.get_playback_info()
                    controls = info.controls if info else None
                    capabilities = frozenset(name for name, (flag, _) in COMMANDS.items()
                                             if controls and getattr(controls, flag, False))
                    if self.metadata_dirty:
                        self.metadata_dirty = False
                        properties = await asyncio.wait_for(session.try_get_media_properties_async(), 4)
                        updated = Track(properties.title or "", properties.artist or "", properties.album_title or "")
                        if updated.identity != track.identity:
                            cover = b""
                            self.snapshot.emit(None)
                        track = updated
                        try:
                            cover = await asyncio.wait_for(self.artwork(properties), 2)
                        except (OSError, RuntimeError, TimeoutError, TypeError):
                            cover = b""
                    now = monotonic()
                    timeline = relative_timeline(info, session.get_timeline_properties(), datetime.now(timezone.utc))
                    if track.title:
                        track = Track(track.title, track.artist, track.album, timeline.duration)
                        snapshot = Snapshot(identity, track, timeline, info.playback_status.name if info else "",
                                            capabilities, cover, bool(info and info.is_shuffle_active),
                                            bool(info and info.auto_repeat_mode and info.auto_repeat_mode.value),
                                            now - last_poll > 20, now)
                        self.snapshot.emit(snapshot)
                        previous = snapshot
                    elif previous is not None:
                        self.snapshot.emit(None)
                        previous = None
                    last_poll = now
                elif previous is not None:
                    previous = None
                    self.snapshot.emit(None)
                while True:
                    try:
                        name, value = self.commands.get_nowait()
                    except Empty:
                        break
                    if session:
                        await self.execute(session, capabilities, name, value)
            except (OSError, RuntimeError, TimeoutError, AttributeError) as error:
                LOGGER.warning("Sessão de mídia indisponível (%s)", type(error).__name__)
                for remove, token in subscriptions:
                    try:
                        remove(token)
                    except OSError:
                        pass
                subscriptions.clear()
                if manager and manager_token is not None:
                    try:
                        manager.remove_sessions_changed(manager_token)
                    except OSError:
                        pass
                session = manager = previous = manager_token = None
                self.snapshot.emit(None)
            try:
                delay = 2.5 if self.visible and previous and previous.timeline.playing else 8
                await asyncio.wait_for(self.changed.wait(), delay)
            except TimeoutError:
                pass
        for remove, token in subscriptions:
            try:
                remove(token)
            except OSError:
                pass
        if manager and manager_token is not None:
            try:
                manager.remove_sessions_changed(manager_token)
            except OSError:
                pass
