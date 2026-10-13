"""Static defaults for phase P1 (the JSON config file arrives in P3)."""

ALLOWLIST = frozenset({"windowsterminal.exe"})  # lower-case process exe names
REQUIRE_SHIFT = True
MIN_DRAG_PX = 4
ICON_SIZE = 24  # logical px at 100% DPI
ICON_OFFSET = 10  # logical px from the mouse-up point
ICON_TIMEOUT_MS = 4000
POLL_INTERVAL_MS = 15
WATCHDOG_INTERVAL_MS = 2000
WATCHDOG_STALE_TICKS = 3
