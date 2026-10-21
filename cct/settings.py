"""User settings persisted as JSON in %APPDATA%/ClaudeCliTranslate/settings.json.

Every key is validated on load (bad values fall back to the default), so a hand-edited or corrupt
file can never break start-up. Writes are atomic.
"""
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

LANGUAGES = (("ru", "Russian"), ("en", "English"), ("de", "German"), ("fr", "French"),
             ("es", "Spanish"), ("it", "Italian"), ("pt", "Portuguese"), ("uk", "Ukrainian"),
             ("pl", "Polish"), ("tr", "Turkish"), ("zh-CN", "Chinese (Simplified)"),
             ("ja", "Japanese"), ("ko", "Korean"))
SCOPES = ("terminals", "all")
PROXY_MODES = ("auto", "direct", "system")
DEFAULT_ALLOWLIST = ("windowsterminal.exe",)
# Classic console windows report their SHELL as the owning process (cmd.exe, powershell.exe, ...), so they
# are matched by window class instead. Measured with tools/probe_host.py.
DEFAULT_CLASSES = ("consolewindowclass",)

# Claude models offered for the Claude icon: (API model id, short name). Cheapest / fastest first.
CLAUDE_MODELS = (("claude-haiku-5-5", "Haiku 5.5 (fast, cheapest)"),
                 ("claude-sonnet-5-5", "Sonnet 5.5 (better)"),
                 ("claude-opus-5-5", "Opus 5.5 (best)"))
DEFAULT_CLAUDE_MODEL = CLAUDE_MODELS[0][0]
MAX_KEY_CHARS = 300

AUTO_LANG = "auto"  # source language "detect automatically" (Write / Paste window only)

DEFAULTS = {
    "font_px": DEFAULT_FONT_PX,
    "target_lang": "ru",
    "scope": "terminals",
    "enabled": True,
    "proxy_mode": "auto",
    "allowlist": list(DEFAULT_ALLOWLIST),
    "allowlist_classes": list(DEFAULT_CLASSES),
    "first_run_done": False,
    # Claude translation engine (second floating icon)
    "claude_icon": True,
    "claude_model": DEFAULT_CLAUDE_MODEL,
    "claude_api_key": "",  # optional; ANTHROPIC_API_KEY in the environment is used when this is empty
    # Write / Paste window
    "writer_src": AUTO_LANG,
    "writer_dst": "en",
    "writer_font_in": DEFAULT_FONT_PX,
    "writer_font_out": DEFAULT_FONT_PX,
}


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


def valid_lang(value, default=None) -> str:
    codes = {code.lower(): code for code, _name in LANGUAGES}
    if isinstance(value, str) and value.lower() in codes:
        return codes[value.lower()]
    return default or DEFAULTS["target_lang"]


def clean_classes(value) -> list:
    """Lower-cased, de-duplicated window class names; invalid input falls back to the default, [] is allowed."""
    if not isinstance(value, list):
        return list(DEFAULT_CLASSES)
    out = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip().lower() not in out:
            out.append(item.strip().lower())
    return out


def clean_allowlist(value) -> list:
    """Lower-cased, de-duplicated exe names; an empty or invalid list falls back to the default."""
    if not isinstance(value, list):
        return list(DEFAULT_ALLOWLIST)
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            name = os.path.basename(item.strip().replace("\\", "/")).lower()
            if name and name not in out:
                out.append(name)
    return out or list(DEFAULT_ALLOWLIST)


def normalize(data) -> dict:
    """Validate a decoded JSON object into a complete settings dict."""
    out = dict(DEFAULTS)
    out["allowlist"] = list(DEFAULT_ALLOWLIST)
    out["allowlist_classes"] = list(DEFAULT_CLASSES)
    if not isinstance(data, dict):
        return out
    if "font_px" in data:
        out["font_px"] = snap_font(data["font_px"])
    if "target_lang" in data:
        out["target_lang"] = valid_lang(data["target_lang"])
    if data.get("scope") in SCOPES:
        out["scope"] = data["scope"]
    if data.get("proxy_mode") in PROXY_MODES:
        out["proxy_mode"] = data["proxy_mode"]
    if "allowlist" in data:
        out["allowlist"] = clean_allowlist(data["allowlist"])
    if "allowlist_classes" in data:
        out["allowlist_classes"] = clean_classes(data["allowlist_classes"])
    if isinstance(data.get("writer_src"), str):
        out["writer_src"] = AUTO_LANG if data["writer_src"].lower() == AUTO_LANG else valid_lang(
            data["writer_src"], AUTO_LANG)
    if "writer_dst" in data:
        out["writer_dst"] = valid_lang(data["writer_dst"], DEFAULTS["writer_dst"])
    for key in ("writer_font_in", "writer_font_out"):
        if key in data:
            out[key] = snap_font(data[key])
    if data.get("claude_model") in dict(CLAUDE_MODELS):
        out["claude_model"] = data["claude_model"]
    if isinstance(data.get("claude_api_key"), str):
        out["claude_api_key"] = data["claude_api_key"].strip()[:MAX_KEY_CHARS]
    for key in ("enabled", "first_run_done", "claude_icon"):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    return out


def window_allowed(exe: str, window_class: str, settings: dict) -> bool:
    """Whether the foreground window (lower-case exe name and class) may trigger the app under these settings."""
    if not settings.get("enabled", True) or not (exe or window_class):
        return False
    if settings.get("scope") == "all":
        return True
    return bool(exe and exe in settings.get("allowlist", DEFAULT_ALLOWLIST)) or bool(
        window_class and window_class in settings.get("allowlist_classes", DEFAULT_CLASSES))


def load(path: str = PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return normalize(json.load(f))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log.warning("settings unreadable (%s); using defaults", type(exc).__name__)
    return normalize(None)


def save(settings: dict, path: str = PATH) -> None:
    """Atomic write: temp file in the same folder, then os.replace."""
    try:
        folder = os.path.dirname(path) or "."
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(normalize(settings), f, indent=2)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
    except OSError as exc:
        log.warning("settings could not be saved (%s)", type(exc).__name__)
