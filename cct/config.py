"""Static constants. User-changeable options (language, scope, allowlist, proxy_mode, ...) live in cct.settings."""

ALLOWLIST = frozenset({"windowsterminal.exe"})  # fallback only; the live allowlist is in settings.json
REQUIRE_SHIFT = True
MIN_DRAG_PX = 4
ICON_SIZE = 40  # logical px at 100% DPI
ICON_OFFSET = 10  # logical px from the mouse-up point
POLL_INTERVAL_MS = 15
WATCHDOG_INTERVAL_MS = 2000
WATCHDOG_STALE_TICKS = 3

# Phase 2: selection read, normalisation, translation, popup
TARGET_LANG = "ru"
PROXY_MODE = "auto"  # auto | direct | system
MAX_CHARS = 5000
UIA_FIRST_DELAY_MS = 60
UIA_RETRY_DELAY_MS = 250
UIA_READ_TIMEOUT_MS = 500
CONNECT_TIMEOUT_S = 5
READ_TIMEOUT_S = 10
CACHE_SIZE = 100
POPUP_MAX_WIDTH = 360
POPUP_MAX_HEIGHT = 260
