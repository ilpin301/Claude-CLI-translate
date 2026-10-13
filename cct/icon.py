"""Non-activating translate icon placed in physical pixels with SetWindowPos."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer, Signal
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


class IconWindow(QWidget):
    clicked = Signal()

    def __init__(self):
        super().__init__(
            None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.resize(config.ICON_SIZE, config.ICON_SIZE)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_icon)
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

    def show_near(self, px: int, py: int) -> None:
        work, scale = winutil.monitor_at(px, py)
        size = round(config.ICON_SIZE * scale)
        offset = round(config.ICON_OFFSET * scale)
        x, y = clamp_rect(px + offset, py + offset, size, size, work)
        self.show()
        self._apply_ex_style()
        user32.SetWindowPos(self._hwnd(), HWND_TOPMOST, x, y, size, size, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        self._timer.start(config.ICON_TIMEOUT_MS)

    def hide_icon(self) -> None:
        self._timer.stop()
        self.hide()

    def contains_physical(self, x: int, y: int) -> bool:
        return self.isVisible() and point_in_rect(x, y, winutil.window_rect(self._hwnd()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2d6cdf"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)
        painter.setPen(QColor("white"))
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, "A文")
