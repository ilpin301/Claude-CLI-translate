"""Pure geometry helpers; all values are physical pixels, rects are (left, top, right, bottom)."""
from typing import Tuple

Rect = Tuple[int, int, int, int]


def clamp_rect(x: int, y: int, w: int, h: int, work: Rect) -> Tuple[int, int]:
    """Top-left position that keeps a w*h rect inside the work area (left/top win if it cannot fit)."""
    left, top, right, bottom = work
    x = max(left, min(x, right - w))
    y = max(top, min(y, bottom - h))
    return x, y


def point_in_rect(px: int, py: int, rect: Rect) -> bool:
    left, top, right, bottom = rect
    return left <= px < right and top <= py < bottom
