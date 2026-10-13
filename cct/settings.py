"""User settings persisted as JSON in %APPDATA%/ClaudeCliTranslate/settings.json (popup font size for now)."""
import json
import logging
import os
import tempfile

log = logging.getLogger("cct.settings")

APP_DIR = os.path.join(os.environ.get("APPDATA", "."), "ClaudeCliTranslate")
PATH = os.path.join(APP_DIR, "settings.json")

BASE_FONT_PX = 13  # popup width / max height in config.py are defined for this size
DEFAULT_FONT_PX = 16
MIN_FONT_PX = 10
MAX_FONT_PX = 40
FONT_SIZES = ((13, "Small"), (16, "Medium"), (19, "Large"), (23, "Extra large"))


def clamp_font(px) -> int:
    try:
        value = int(px)
    except (TypeError, ValueError):
        return DEFAULT_FONT_PX
    return max(MIN_FONT_PX, min(MAX_FONT_PX, value))


def snap_font(px) -> int:
    """Nearest size offered in the tray menu (ties go to the smaller one)."""
    value = clamp_font(px)
    return min((size for size, _label in FONT_SIZES), key=lambda size: (abs(size - value), size))


def load(path: str = PATH) -> dict:
    settings = {"font_px": DEFAULT_FONT_PX}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "font_px" in data:
            settings["font_px"] = snap_font(data["font_px"])
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log.warning("settings unreadable (%s); using defaults", type(exc).__name__)
    return settings


def save(settings: dict, path: str = PATH) -> None:
    """Atomic write: temp file in the same folder, then os.replace."""
    try:
        folder = os.path.dirname(path) or "."
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"font_px": clamp_font(settings.get("font_px"))}, f)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
    except OSError as exc:
        log.warning("settings could not be saved (%s)", type(exc).__name__)
