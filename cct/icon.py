"""Non-activating translate icons (Google and GLM, side by side) placed in physical pixels with SetWindowPos.

Each icon is its own small window, so one can be clicked or dismissed (left click = translate with that
engine, right click = dismiss) while the other stays where it is.
"""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from . import config, winutil
from .geometry import clamp_rect, point_in_rect

user32 = ctypes.WinDLL("user32")
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


GOOGLE = "google"
GLM = "glm"
ENGINE_COLORS = {GOOGLE: "#2d6cdf", GLM: "#6a4bd8"}
BAR_COLORS = {GOOGLE: "#3e5c86", GLM: "#5a4d86"}  # muted versions of the same colours, for the popup title bar
_TIPS = {GOOGLE: "Translate with Google", GLM: "Translate with GLM"}
ICON_GAP = 6  # logical px between the icons


class IconWindow(QWidget):
    clicked = Signal()

    def __init__(self, engine: str = GOOGLE):
        super().__init__(
            None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.engine = engine
        self.resize(config.ICON_SIZE, config.ICON_SIZE)
        self.setToolTip(_TIPS[engine])
        self._styled = False

    def _hwnd(self) -> int:
        return int(self.winId())

    def _apply_ex_style(self) -> None:
        if self._styled:
            return
        hwnd = self._hwnd()
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        self._styled = True

    def place(self, x: int, y: int, size: int) -> None:
        """Show the icon with its top-left corner at the physical point (x, y)."""
        self.show()
        self._apply_ex_style()
        user32.SetWindowPos(self._hwnd(), HWND_TOPMOST, x, y, size, size, SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def hide_icon(self) -> None:
        self.hide()

    def contains_physical(self, x: int, y: int) -> bool:
        return self.isVisible() and point_in_rect(x, y, winutil.window_rect(self._hwnd()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.RightButton:
            self.hide_icon()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(ENGINE_COLORS[self.engine]))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)
        if self.engine == GLM:
            self._paint_label(painter)
            return
        painter.setPen(QColor("white"))
        font = QFont("Segoe UI")
        font.setPixelSize(round(self.height() * 0.45))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, "A文")

    def _paint_label(self, painter: QPainter) -> None:
        painter.setPen(QColor("white"))
        font = QFont("Segoe UI")
        font.setPixelSize(round(self.height() * 0.32))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, "GLM")


class IconBar:
    """Both icons next to the selection point; either can be dismissed or used independently."""

    def __init__(self):
        self.windows = {GOOGLE: IconWindow(GOOGLE), GLM: IconWindow(GLM)}

    def show_near(self, px: int, py: int, engines) -> None:
        engines = [name for name in (GOOGLE, GLM) if name in engines]
        work, scale = winutil.monitor_at(px, py)
        size = round(config.ICON_SIZE * scale)
        gap = round(ICON_GAP * scale)
        offset = round(config.ICON_OFFSET * scale)
        width = size * len(engines) + gap * max(len(engines) - 1, 0)
        x, y = clamp_rect(px + offset, py + offset, width, size, work)  # the pair is kept on screen together
        for name, win in self.windows.items():
            if name in engines:
                win.place(x, y, size)
                x += size + gap
            else:
                win.hide_icon()

    def hide_icon(self, engine=None) -> None:
        """Hide one icon, or both when engine is None."""
        for name, win in self.windows.items():
            if engine is None or name == engine:
                win.hide_icon()

    def contains_physical(self, x: int, y: int) -> bool:
        return any(win.contains_physical(x, y) for win in self.windows.values())
