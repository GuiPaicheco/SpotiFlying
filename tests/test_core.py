from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from PySide6.QtCore import QRect, QSize

from spotiflying.lyrics import CatalogError, LyricsProvider, normalize, parse, select
from spotiflying.overlay import geometry
from spotiflying.playback import Track, relative_timeline
from spotiflying.settings import Settings, atomic_json, read_json, validated
from spotiflying.sync import Playhead, Timeline


def test_lrc_unicode_multiple_offset_and_instrumental():
    text = "\ufeff[ar:Lia]\n[offset:+200]\n[00:03][00:06.10]Olá 世界\n[00:02.1]\n[00:99.11]malformed"
    lyric = parse(text)
    assert [(cue.at, cue.text) for cue in lyric.cues] == [(2100, ""), (3000, "Olá 世界"), (6100, "Olá 世界")]
    assert lyric.index(1899) == -1
    assert lyric.index(2800) == 1
    assert lyric.index(2700, 100) == 1
    assert lyric.index(2800, -100) == 0
    assert parse("[offset:-200]\n[00:03]late").index(3199) == -1
    assert parse("[00:03]Olá", timed=False).text == "[00:03]Olá"
    assert parse("[ar:Name]\n[00:01]").status == "instrumental"


def test_extended_word_timestamps_and_repeat():
    lyric = parse("[00:02.00][00:05]<00:02.00>Deixo <00:02.5>passar")
    assert lyric.cues[0].words == ((2000, 0), (2500, 6))
    assert lyric.cues[1].words == ((5000, 0), (5500, 6))
    assert not parse("[00:02]<00:03>Deixo <00:02.5>passar").cues[0].words


def row(title, album, duration):
    return {"trackName": title, "artistName": "Lía", "albumName": album, "duration": duration,
            "syncedLyrics": "[00:00]Oi"}


def test_versions_and_ambiguity():
    track = Track("Marés", "Lía", "Cartas", 20001)
    correct = row("MARÉS", "Cartas", 20)
    assert normalize("  Ａ ç–b  ") == "a ç b"
    assert select(track, [row("Marés (Live)", "Cartas", 20), row("Marés", "Cartas Remix", 20), correct]) == correct
    assert select(track, [row("Marés", "Cartas", 24)]) is None
    assert select(track, [row("Marés", "Cartas", 20), row("Marés", "Cartas", 20.1)]) is None
    assert select(Track("Marés", "Lía", "Cartas"), [correct]) is None


def test_catalog_exact_and_ambiguous_fallback():
    track = Track("Marés", "Lía", "Cartas", 20001)

    def transport(path, params):
        if path == "get-cached":
            assert params["duration"] == 20
            raise HTTPError("", 404, "", {}, None)
        return [row("Marés", "Cartas", 20), row("Marés", "Cartas", 20.1)]

    provider = LyricsProvider(transport)
    result, choices = provider.lookup(track, lambda: False)
    assert result.status == "missing" and len(choices) == 2
    assert provider.lookup(track, lambda: True)[1] == []


@pytest.mark.parametrize("failure,delay", [(HTTPError("", 429, "", {"Retry-After": "65"}, None), 65),
                                            (HTTPError("", 503, "", {}, None), 15),
                                            (TimeoutError(), 15), (ValueError(), 15)])
def test_catalog_failures(failure, delay):
    def transport(*_):
        raise failure

    provider = LyricsProvider(transport, lambda: 11)
    with pytest.raises(CatalogError):
        provider.lookup(Track("Mar", "Lía"), lambda: False)
    assert provider.retry_at == 11 + delay
    with pytest.raises(CatalogError, match="intervalo"):
        provider.lookup(Track("Mar", "Lía"), lambda: False)


def test_playhead_pause_seek_loss_and_rate():
    now = [0]
    head = Playhead(lambda: now[0])
    head.update(Timeline(0, 9000, True, 1.5), True)
    now[0] = 1
    assert head.position() == 1500
    head.update(Timeline(1600, 9000, True, 1.5))
    assert head.position() == 1500
    now[0] = 2
    assert head.position() == 3100
    assert head.update(Timeline(5000, 9000, False))
    now[0] = 200
    assert head.position() == 5000
    assert head.update(Timeline(1000, 9000, False))
    assert head.position() == 1000
    head.update(Timeline(), True)
    assert head.position() is None
    assert head.update(Timeline(8500, 9000, True), True)
    now[0] = 201
    assert head.position() == 9000


def test_nonzero_winrt_start_and_state():
    now = datetime.now(timezone.utc)
    info = SimpleNamespace(playback_status=SimpleNamespace(name="PLAYING"), playback_rate=2)
    properties = SimpleNamespace(start_time=timedelta(seconds=5), end_time=timedelta(seconds=25),
                                 position=timedelta(seconds=10), last_updated_time=now - timedelta(seconds=1))
    assert relative_timeline(info, properties, now) == Timeline(7000, 20000, True, 2)
    info.playback_status.name = "PAUSED"
    assert relative_timeline(info, properties, now) == Timeline(5000, 20000, False, 2)


def test_settings_backup_migration_and_profiles(tmp_path):
    cfg = Settings(tmp_path)
    cfg.data["offset"] = 50
    cfg.save()
    cfg.data["offset"] = -50
    cfg.save()
    cfg.path.write_text("{?", encoding="utf-8")
    restored = Settings(tmp_path)
    assert restored.recovered and restored.data["offset"] == 50
    restored.data["associations"] = {"test": "C:/secret.lrc"}
    restored.data["history"] = ["secret"]
    profile = tmp_path / "profile.json"
    restored.export_profile(profile)
    assert {"history", "associations", "catalog"}.isdisjoint(read_json(profile))
    assert validated({"version": 0, "visual": {"width": 10000}, "offset": 9000})["offset"] == 0
    with pytest.raises(ValueError):
        validated({"version": 99})
    with pytest.raises(TypeError):
        atomic_json(profile, {"bad": object()})
    assert read_json(profile)["offset"] == 50


def test_negative_monitor_geometry_and_clamp():
    area = QRect(-1600, 40, 1600, 900)
    assert geometry(area, QSize(240, 56), {}, "card") == QRect(-264, 860, 240, 56)
    assert geometry(area, QSize(500, 1000), {"anchor": "tl", "x": -500, "y": 900}, "lyrics") == QRect(
        -1600, 40, 500, 900)
