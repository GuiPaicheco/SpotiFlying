"""Timed text parsing, track identification, and the optional catalog."""
import json
import random
import re
import time
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

STAMP = r"(\d{1,4}):([0-5]\d)(?:[.:](\d{1,3}))?"
LINE = re.compile(r"\[" + STAMP + r"\]")
WORD = re.compile(r"<" + STAMP + r">")
OFFSET = re.compile(r"\[offset:\s*([+-]?\d{1,9})\s*\]", re.I)
TAGS = re.compile(r"^\s*\[[a-z]+:.*\]\s*$", re.I)


def milliseconds(mark):
    minute, second, fraction = mark.groups()
    return (int(minute) * 60 + int(second)) * 1000 + int((fraction or "").ljust(3, "0"))


@dataclass(frozen=True)
class Cue:
    at: int
    text: str
    words: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Lyrics:
    status: str
    text: str = ""
    cues: tuple[Cue, ...] = ()
    offset: int = 0
    source: str = ""

    def index(self, position, adjustment=0):
        return bisect_right(self.cues, position + adjustment + self.offset, key=lambda cue: cue.at) - 1


def parse(text, source="", timed=True):
    text = text.lstrip("\ufeff")
    offset = 0
    cues = []
    plain = []
    for line in text.splitlines():
        setting = OFFSET.fullmatch(line.strip()) if timed else None
        if setting:
            offset = int(setting[1])
            continue
        marks = []
        body = line.strip()
        while timed and (mark := LINE.match(body)):
            marks.append(milliseconds(mark))
            body = body[mark.end():]
        if not marks:
            if not timed or not TAGS.fullmatch(line):
                plain.append(line)
            continue
        parts = []
        words = []
        start = 0
        for mark in WORD.finditer(body):
            parts.append(body[start:mark.start()])
            words.append((milliseconds(mark), sum(map(len, parts))))
            start = mark.end()
        parts.append(body[start:])
        displayed = "".join(parts)
        for at in marks:
            shifted = tuple((stamp + at - marks[0], index) for stamp, index in words)
            valid = all(stamp >= at for stamp, _ in shifted) and all(
                a[0] < b[0] and a[1] < b[1] for a, b in zip(shifted, shifted[1:])
            )
            cues.append(Cue(at, displayed, shifted if valid else ()))
    if cues:
        cues.sort(key=lambda cue: cue.at)
        complete = "\n".join(cue.text for cue in cues).strip()
        return Lyrics("sync" if complete else "instrumental", complete, tuple(cues), offset, source)
    complete = "\n".join(plain).strip()
    return Lyrics("static" if complete else "missing", complete, source=source)


def normalize(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


VERSION = {"live", "remix", "acoustic", "acústico", "remaster", "remastered", "demo", "edit", "version",
           "instrumental", "karaoke", "cover", "ao vivo"}


def versions(value):
    normalized = normalize(value)
    return {marker for marker in VERSION if f" {marker} " in f" {normalized} "}


def track_key(title, artist, album, duration):
    return "|".join((normalize(title), normalize(artist), normalize(album), str(round(duration / 1000))))


def select(track, candidates):
    matches = []
    for row in candidates:
        title, artist, album = (str(row.get(k) or "") for k in ("trackName", "artistName", "albumName"))
        seconds = row.get("duration")
        if not isinstance(seconds, (int, float)) or not 0 < seconds < 86400 or not track.duration:
            continue
        if normalize(track.title) != normalize(title) or normalize(track.artist) != normalize(artist):
            continue
        if versions(track.title + " " + track.album) != versions(title + " " + album):
            continue
        gap = abs(track.duration / 1000 - seconds)
        if gap <= 3:
            same_album = bool(track.album and normalize(track.album) == normalize(album))
            matches.append((10 * same_album - gap, row))
    matches.sort(key=lambda item: item[0], reverse=True)
    if matches and (len(matches) == 1 or matches[0][0] - matches[1][0] >= 1.5):
        return matches[0][1]
    return None


def from_catalog(row):
    if row.get("instrumental") is True:
        return Lyrics("instrumental", source="LRCLIB")
    for field, timed in (("syncedLyrics", True), ("plainLyrics", False)):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return parse(value, "LRCLIB", timed)
    return Lyrics("missing", source="LRCLIB")


class CatalogError(Exception):
    pass


def retry_delay(header):
    if not header:
        return 30
    try:
        return max(1, min(2_147_483_647, int(header)))
    except ValueError:
        try:
            deadline = parsedate_to_datetime(header)
            return max(1, (deadline - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 30


class LyricsProvider:
    def __init__(self, transport=None, clock=time.monotonic, jitter=random.uniform):
        self.transport = transport or self.request
        self.clock = clock
        self.jitter = jitter
        self.retry_at = 0

    @staticmethod
    def request(path, params):
        request = Request(
            "https://lrclib.net/api/" + path + "?" + urlencode(params),
            headers={"User-Agent": "SpotiFlying/1.0 (+https://github.com/GuiPaicheco/SpotiFlying)"},
        )
        with urlopen(request, timeout=5) as reply:
            payload = reply.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError("Resposta grande demais")
        return json.loads(payload)

    def lookup(self, track, cancelled):
        if self.clock() < self.retry_at:
            raise CatalogError("A consulta está no intervalo de espera.")
        params = {"track_name": track.title, "artist_name": track.artist}
        if track.album:
            params["album_name"] = track.album
        try:
            if track.duration and track.album:
                try:
                    exact = self.transport("get-cached", {**params, "duration": round(track.duration / 1000)})
                except HTTPError as error:
                    if error.code != 404:
                        raise
                else:
                    if not isinstance(exact, dict):
                        raise ValueError("Resposta inválida")
                    if select(track, [exact]):
                        result = from_catalog(exact)
                        if result.status != "missing":
                            return result, []
            if cancelled():
                return Lyrics("missing"), []
            try:
                rows = self.transport("search", params)
            except HTTPError as error:
                if error.code == 404:
                    return Lyrics("missing"), []
                raise
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Resposta inválida")
            selected = select(track, rows)
            return (from_catalog(selected), []) if selected else (Lyrics("missing"), rows[:20])
        except HTTPError as error:
            delay = 15
            if error.code == 429:
                delay = retry_delay(error.headers.get("Retry-After") if error.headers else None)
                delay += self.jitter(0, min(10, delay * .2))
            self.retry_at = self.clock() + delay
            raise CatalogError(f"Catálogo indisponível (HTTP {error.code}).") from error
        except (TimeoutError, URLError) as error:
            self.retry_at = self.clock() + 15
            timed_out = isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)
            raise CatalogError("O catálogo demorou para responder." if timed_out else "Catálogo inacessível.") from error
        except ValueError as error:
            self.retry_at = self.clock() + 15
            raise CatalogError("O catálogo retornou uma resposta inválida.") from error
        except OSError as error:
            self.retry_at = self.clock() + 15
            raise CatalogError("Falha de rede ao consultar o catálogo.") from error
