"""Pure logic: turns raw left-button events into Shift+drag triggers."""
import math
from dataclasses import dataclass
from typing import Optional, Tuple

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

# (message, x, y, tick_ms, shift_down) - coordinates are physical pixels
Event = Tuple[int, int, int, int, bool]


@dataclass(frozen=True)
class Trigger:
    x: int
    y: int
    drag_px: float


class Gate:
    def __init__(self, require_shift: bool = True, min_drag_px: int = 4):
        self.require_shift = require_shift
        self.min_drag_px = min_drag_px
        self._down: Optional[Tuple[int, int, bool]] = None

    def reset(self) -> None:
        self._down = None

    def feed(self, ev: Event) -> Optional[Trigger]:
        msg, x, y, _tick, shift = ev
        if msg == WM_LBUTTONDOWN:
            self._down = (x, y, shift)
            return None
        if msg == WM_LBUTTONUP and self._down is not None:
            dx, dy, down_shift = self._down
            self._down = None
            drag = math.hypot(x - dx, y - dy)
            if drag < self.min_drag_px:
                return None
            # Shift is accepted at button-down OR button-up (tolerates scheduling skew).
            if self.require_shift and not (down_shift or shift):
                return None
            return Trigger(x, y, drag)
        return None
