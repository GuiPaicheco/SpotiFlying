"""Profile schema and atomic user data persistence."""
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile

VERSION = 1
ITEMS = ["Capa", "Título", "Artista", "Álbum", "Progresso", "Tempo atual", "Tempo restante",
         "Duração", "Fonte", "Ícone", "Estado", "Próxima linha", "Controles"]
STORIES = {
    "font": "Segoe UI", "size": 38, "weight": 900, "uppercase": True, "italic": False,
    "tracking": 0, "spacing": -3, "emphasis": 1.75, "shadow": True, "outline": 0, "color": "#ffffff",
    "secondary": "#b1d6cf", "gradient": False, "art_tint": False, "opacity": 100,
    "background": "#182421", "background_alpha": 0, "border": 0, "padding": 0,
    "width": 32, "height": 50, "units": "Percentual", "x_align": "Esquerda", "y_align": "Topo",
    "lines": 1, "previous": 0, "mode": "Linha", "wrap": True, "scroll": False,
    "animation": "Fade e slide", "motion_ms": 160, "intensity": 6, "easing": "Suave",
    "phrase_progress": False,
    "card_width": 240, "card_height": 56, "cover": 40, "card_opacity": 100, "card_radius": 13,
    "card_padding": 8, "card_spacing": 8, "card_border": 1, "card_shadow": False,
    "card_align": "Esquerda", "card_layout": "Horizontal",
    "card_items": ["Capa", "Título", "Artista"], "item_order": ITEMS,
    "autohide": "Nunca",
}
PRESETS = {
    "Stories": {},
    "Minimal": {"size": 21, "weight": 600, "uppercase": False, "wrap": False, "emphasis": 1.0},
    "Karaokê": {"mode": "Palavra", "lines": 3, "previous": 1, "size": 28, "uppercase": False,
                "emphasis": 1.0, "phrase_progress": True},
    "Glass": {"background_alpha": 69, "padding": 16, "border": 1, "weight": 700, "size": 32},
    "Compacto": {"size": 24, "emphasis": 1.3, "width": 25, "card_width": 205,
                 "card_height": 48, "cover": 32},
    "Personalizado": {},
}
DEFAULT = {
    "version": VERSION, "preset": "Stories", "visual": STORIES, "presets": {}, "theme": "Sistema",
    "lyrics_visible": True, "card_visible": True, "topmost": True, "group": False,
    "persistent": False, "interaction_seconds": 12, "offset": 0, "track_offsets": {},
    "emphases": {}, "associations": {}, "catalog": False, "history_enabled": False, "history": [],
    "monitor": "", "lyrics_position": {}, "card_position": {}, "fps": 30, "reduced_motion": False,
    "economy": False, "toggle_hotkey": "Ctrl+Alt+L", "interact_hotkey": "Ctrl+Alt+I",
    "startup": False, "intro_seen": False,
}
PROFILE = ("preset", "visual", "presets", "theme", "lyrics_visible", "card_visible", "topmost",
           "group", "monitor", "lyrics_position", "card_position", "fps", "reduced_motion", "economy", "offset")
RANGES = {
    "size": (9, 145), "weight": (100, 900), "tracking": (-5, 24), "spacing": (-16, 45),
    "emphasis": (1, 2.5), "outline": (0, 8), "opacity": (10, 100), "background_alpha": (0, 100),
    "border": (0, 8), "padding": (0, 60), "width": (10, 2400), "height": (10, 1800),
    "lines": (1, 12), "previous": (0, 11), "motion_ms": (0, 900), "intensity": (0, 40),
    "card_width": (110, 800), "card_height": (44, 480), "cover": (16, 180),
    "card_opacity": (15, 100), "card_radius": (0, 40), "card_padding": (0, 40),
    "card_spacing": (0, 35), "card_border": (0, 6), "fps": (10, 60), "offset": (-5000, 5000),
    "interaction_seconds": (3, 180),
}
CHOICES = {
    "theme": ("Sistema", "Escuro", "Claro"), "units": ("Percentual", "DIP"),
    "x_align": ("Esquerda", "Centro", "Direita"), "card_align": ("Esquerda", "Centro", "Direita"),
    "y_align": ("Topo", "Centro", "Base"), "mode": ("Linha", "Palavra", "Página", "Palavra estimada"),
    "animation": ("Nenhuma", "Fade", "Slide", "Fade e slide", "Escala", "Bounce", "Revelação"),
    "easing": ("Linear", "Suave"), "card_layout": ("Horizontal", "Vertical"),
    "autohide": ("Nunca", "Sem reprodução", "Inatividade", "Cursor fora"), "preset": tuple(PRESETS),
}


def bounded(value, default, key):
    if key == "emphasis" and type(value) in (int, float):
        value = float(value)
    if type(value) is not type(default):
        return deepcopy(default)
    if key in RANGES:
        low, high = RANGES[key]
        return value if low <= value <= high else default
    if key in CHOICES:
        return value if value in CHOICES[key] else default
    if key in ("color", "secondary", "background"):
        try:
            if len(value) == 7 and value[0] == "#":
                int(value[1:], 16)
                return value
        except ValueError:
            pass
        return default
    if key in ("card_items", "item_order"):
        items = list(dict.fromkeys(item for item in value if isinstance(item, str) and item in ITEMS))
        return items + [item for item in ITEMS if item not in items] if key == "item_order" else items
    if isinstance(value, str):
        return value[:256]
    return deepcopy(value)


def visual_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    result = {key: bounded(raw.get(key), default, key) for key, default in STORIES.items()}
    if result["units"] == "Percentual":
        result["width"] = min(100, result["width"])
        result["height"] = min(100, result["height"])
    return result


def placement(raw):
    if not isinstance(raw, dict):
        return {}
    screen, anchor, x, y = (raw.get(key) for key in ("screen", "anchor", "x", "y"))
    if (isinstance(screen, str) and anchor in ("tl", "center", "br")
            and type(x) is int and type(y) is int and abs(x) <= 32000 and abs(y) <= 32000):
        return {"screen": screen[:256], "anchor": anchor, "x": x, "y": y}
    return {}


def validated(raw):
    if not isinstance(raw, dict):
        raise ValueError("A configuração deve ser um objeto JSON.")
    version = raw.get("version", 0)
    if type(version) is not int or not 0 <= version <= VERSION:
        raise ValueError("Versão de configuração incompatível.")
    result = {key: bounded(raw.get(key), default, key) for key, default in DEFAULT.items()}
    result["version"] = VERSION
    result["visual"] = visual_settings(result["visual"])
    result["presets"] = {name: visual_settings(value) for name, value in result["presets"].items()
                         if name in PRESETS and isinstance(value, dict)}
    for key in ("lyrics_position", "card_position"):
        result[key] = placement(result[key])
    for key in ("track_offsets", "emphases", "associations"):
        limit = 5000 if key == "track_offsets" else 1000
        result[key] = {k: v for k, v in list(result[key].items())[:limit]
                       if isinstance(k, str) and len(k) < 2000
                       and (type(v) is int and -5000 <= v <= 5000 if key == "track_offsets"
                            else isinstance(v, str) and len(v) < 4096)}
    result["history"] = [entry for entry in result["history"][:100] if isinstance(entry, str)]
    return result


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(data, file, indent=2, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            file.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    if path.stat().st_size > 4_000_000:
        raise ValueError("Arquivo de configuração grande demais.")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def paths():
    local = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SpotiFlying"
    if getattr(sys, "frozen", False):
        home = Path(sys.executable).parent
        if (home / "portable.flag").is_file():
            preferred = home / "data"
            try:
                preferred.mkdir(exist_ok=True)
                with NamedTemporaryFile(dir=preferred):
                    pass
                return preferred, False
            except OSError:
                return local, True
    return local, False


class Settings:
    def __init__(self, folder=None):
        self.root, self.fallback = paths() if folder is None else (folder, False)
        self.path = self.root / "config.json"
        self.backup = self.root / "config.backup.json"
        self.recovered = False
        self.data = deepcopy(DEFAULT)
        for path in (self.path, self.backup):
            try:
                self.data = validated(read_json(path))
                self.recovered = path == self.backup
                break
            except (OSError, ValueError):
                pass

    def save(self):
        if self.path.exists():
            try:
                previous = validated(read_json(self.path))
            except (OSError, ValueError):
                previous = None
            if previous:
                atomic_json(self.backup, previous)
        atomic_json(self.path, self.data)

    def preset(self, name, clear=False):
        if clear:
            self.data["presets"].pop(name, None)
        self.data["preset"] = name
        self.data["visual"] = deepcopy(self.data["presets"].get(name, {**STORIES, **PRESETS[name]}))

    def update_visual(self, key, value):
        self.data["visual"][key] = value
        self.data["presets"][self.data["preset"]] = deepcopy(self.data["visual"])

    def export_profile(self, path):
        atomic_json(path, {"version": VERSION, **{key: self.data[key] for key in PROFILE}})

    def import_profile(self, path):
        raw = read_json(path)
        profile = validated(raw)
        self.data.update({key: profile[key] for key in PROFILE if key in raw})
