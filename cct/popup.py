"""Non-activating translation popup (dark rounded panel), placed in physical pixels.

UNTESTED on a real Windows UI: layout sizing, DPI handling and non-activating mouse behaviour
have only been written from the icon.py pattern, never run.

Same window flags / extended styles as icon.py (helpers imported from there). Coordinates in/out are
physical pixels; the only physical -> Qt logical conversion is the size computed in _place().
The copy button is the only clipboard write in the app and happens only on an explicit click.

Movable / resizable: dragging any non-button part of the panel moves it, dragging the corner grip resizes
it (double-click the grip to go back to the automatic size). Both use plain Qt mouse events (logical
coordinates), so no extra Win32 calls are involved. A size chosen by the user is kept for later popups
until the font size changes; a position chosen by the user lasts only for the current popup.
"""
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtGui import QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from . import config, settings, winutil
from .geometry import clamp_rect, point_in_rect
from .icon import (BAR_COLORS, GOOGLE, GWL_EXSTYLE, HWND_TOPMOST, SWP_NOACTIVATE, SWP_SHOWWINDOW,
                   WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, user32)

_MARGIN = 10
_MIN_W, _MIN_H = 220, 90  # smallest size the user can shrink the popup to
_QT_MAX = 16777215  # QWIDGETSIZE_MAX
_GRIP = 16
_RADIUS = 8
_BAR_PAD = 6  # title bar inner padding (logical px)
_BTN_CSS = ("QPushButton{color:white;background:rgba(255,255,255,50);border:none;border-radius:4px;padding:2px 8px;}"
            "QPushButton:hover{background:rgba(255,255,255,90);}")


class _Grip(QWidget):
    """Bottom-right corner handle: drag to resize the popup, double-click to restore the automatic size."""

    def __init__(self, popup: "PopupWindow"):
        super().__init__(popup)
        self._popup = popup
        self._start = None
        self.setFixedSize(_GRIP, _GRIP)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setToolTip("Drag to resize, double-click to reset")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._start = (event.globalPosition().toPoint(), self._popup.begin_resize())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._start is not None and event.buttons() & Qt.LeftButton:
            origin, size = self._start
            delta = event.globalPosition().toPoint() - origin
            self._popup.resize_to(QSize(size.width() + delta.x(), size.height() + delta.y()))

    def mouseReleaseEvent(self, _event) -> None:
        self._start = None

    def mouseDoubleClickEvent(self, _event) -> None:
        self._start = None
        self._popup.reset_size()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#6a6a6a"), 1.5))
        for off in (4, 8, 12):
            painter.drawLine(_GRIP - 2, off, off, _GRIP - 2)


class _TitleBar(QWidget):
    """Coloured strip at the top of the popup (colour = engine); dragging it, or any other free spot, moves the popup."""

    def __init__(self):
        super().__init__()
        self.color = QColor(BAR_COLORS[GOOGLE])
        self.setCursor(Qt.SizeAllCursor)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height() + _RADIUS, _RADIUS, _RADIUS)
        painter.setClipRect(self.rect())  # keep only the top part: rounded top corners, square bottom edge
        painter.fillPath(path, self.color)


class PopupWindow(QWidget):
    retry_requested = Signal()

    def __init__(self, font_px: int = settings.DEFAULT_FONT_PX):
        super().__init__(
            None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self._width = config.POPUP_MAX_WIDTH
        self._max_height = config.POPUP_MAX_HEIGHT
        self._styled = False
        self._anchor = (0, 0)
        self._translation = ""
        self._manual = None  # QSize chosen by the user (manual mode) or None (automatic size)
        self._engine = ""  # engine name shown in the header
        self._moved = False  # the user dragged this popup: keep its position when the content changes
        self._drag = None  # offset of the mouse inside the window while dragging
        self._last = ("", "", "", False, False)  # arguments of the last _set_content, for reset_size()

        self._header = QLabel()
        self._header.setStyleSheet("color:white;font-weight:bold;")
        self._copy = QPushButton("Copy")
        self._retry = QPushButton("Retry")
        self._close = QPushButton("✕")
        for btn in (self._copy, self._retry, self._close):
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setStyleSheet(_BTN_CSS)
            btn.setCursor(Qt.PointingHandCursor)
        self._copy.clicked.connect(self._on_copy)
        self._retry.clicked.connect(self.retry_requested.emit)
        self._close.clicked.connect(self.hide_popup)
        self._bar = _TitleBar()
        top = QHBoxLayout(self._bar)
        top.setContentsMargins(_MARGIN, _BAR_PAD, _BAR_PAD, _BAR_PAD)
        top.addWidget(self._header, 1)
        top.addWidget(self._copy)
        top.addWidget(self._retry)
        top.addWidget(self._close)

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color:#eaeaea;")
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._body)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;}"
                                   "QScrollArea>QWidget>QWidget{background:transparent;}")
        self._note = QLabel()
        self._note.setWordWrap(True)

        content = QVBoxLayout()
        content.setContentsMargins(_MARGIN, 8, _MARGIN, _MARGIN)
        content.setSpacing(6)
        content.addWidget(self._scroll)
        content.addWidget(self._note)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._bar)
        lay.addLayout(content)

        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: self._copy.setText("Copy"))
        self._grip = _Grip(self)
        self.set_font_px(font_px)

    # ---- public API ----

    def set_font_px(self, px: int) -> None:
        """Pixel font size; popup width and max height scale with it. Applies from the next content update."""
        px = settings.clamp_font(px)
        scale = px / settings.BASE_FONT_PX
        self._width = round(config.POPUP_MAX_WIDTH * scale)
        self._max_height = round(config.POPUP_MAX_HEIGHT * scale)
        font = QFont("Segoe UI")
        font.setPixelSize(px)
        self.setFont(font)
        self.setStyleSheet("QLabel, QPushButton {font-family:'Segoe UI'; font-size:%dpx;}" % px)
        self._note.setStyleSheet("color:#9aa0a6;font-size:%dpx;" % max(11, round(px * 0.9)))
        self._manual = None  # the remembered size was for the old font
        self._auto_limits()

    def show_loading(self, px: int, py: int, target: str, engine: str = "", color: str = "") -> None:
        """engine: short name of the translation engine, shown after the languages in the title bar;
        color: the title bar colour (BAR_COLORS of the engine)."""
        self._bar.color = QColor(color or BAR_COLORS[GOOGLE])
        self._bar.update()
        if (px, py) != self._anchor or not self.isVisible():  # same selection and still open (the other engine's
            # icon): keep a dragged position
            self._moved = False
        self._anchor = (px, py)
        self._engine = engine
        self._translation = ""
        self._set_content(self._head("auto", target), "Translating…", "", copy=False)

    def _head(self, source: str, target: str) -> str:
        return "%s → %s%s" % (source, target, " · " + self._engine if self._engine else "")

    def show_result(self, result, truncated: bool, target: str) -> None:
        notes = []
        if result.same_lang:
            notes.append("Source and target language are the same.")
        if truncated:
            notes.append("Text was truncated to %d characters." % config.MAX_CHARS)
        self._translation = result.text
        self._set_content(self._head(result.detected_lang or "auto", target), result.text, " ".join(notes), copy=True)

    def show_error(self, msg: str, retry: bool = False) -> None:
        self._translation = ""
        self._set_content("Translation failed", msg, "", copy=False, retry=retry)

    def hide_popup(self) -> None:
        self._copy_timer.stop()
        self.hide()

    def contains_physical(self, x: int, y: int) -> bool:
        return self.isVisible() and point_in_rect(x, y, winutil.window_rect(self._hwnd()))

    def begin_resize(self) -> QSize:
        """Switch to manual sizing (if not already) and return the current size."""
        if self._manual is None:
            self._manual = self.size()
            self.setMinimumSize(_MIN_W, _MIN_H)
            self.setMaximumSize(_QT_MAX, _QT_MAX)
            self._scroll.setMinimumHeight(20)
            self._scroll.setMaximumHeight(_QT_MAX)
        return self._manual

    def resize_to(self, size: QSize) -> None:
        self._manual = QSize(max(size.width(), _MIN_W), max(size.height(), _MIN_H))
        self.resize(self._manual)

    def reset_size(self) -> None:
        self._manual = None
        self._auto_limits()
        self._set_content(*self._last)

    # ---- internals ----

    def _auto_limits(self) -> None:
        self.setMinimumSize(0, 0)
        self.setMaximumSize(_QT_MAX, _QT_MAX)
        self.setFixedWidth(self._width)

    def _hwnd(self) -> int:
        return int(self.winId())

    def _apply_ex_style(self) -> None:
        if self._styled:
            return
        hwnd = self._hwnd()
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        self._styled = True

    def _set_content(self, header: str, body: str, note: str, copy: bool, retry: bool = False) -> None:
        self._header.setText(header)
        self._copy.setVisible(copy)
        self._retry.setVisible(retry)
        self._copy.setText("Copy")
        self._note.setText(note)
        self._note.setVisible(bool(note))
        self._body.setText(body)
        self._last = (header, body, note, copy, retry)
        if self._manual is not None:
            self.layout().activate()
            self.resize(self._manual)
            self._place()
            return
        inner = self._width - 2 * _MARGIN
        body_h = self._body.heightForWidth(inner - 14)  # 14: scrollbar allowance
        self._scroll.setFixedHeight(min(max(body_h, 20) + 4, self._max_height))
        self.layout().activate()
        self.resize(self._width, self.layout().sizeHint().height())
        self._place()

    def _place(self) -> None:
        if self._moved:  # keep where the user put it
            px, py = winutil.window_rect(self._hwnd())[:2]
            offset = 0
        else:
            (px, py), offset = self._anchor, config.ICON_OFFSET
        work, scale = winutil.monitor_at(px, py)
        # the one logical -> physical conversion (mirrors icon.py)
        w = round(self.width() * scale)
        h = round(self.height() * scale)
        x, y = clamp_rect(px, py + round(offset * scale), w, h, work)
        self.show()
        self._apply_ex_style()
        user32.SetWindowPos(self._hwnd(), HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def _on_copy(self) -> None:
        if not self._translation:
            return
        QApplication.clipboard().setText(self._translation)
        self._copy.setText("Copied")
        self._copy_timer.start(1200)

    def resizeEvent(self, _event) -> None:
        self._grip.move(self.width() - _GRIP - 3, self.height() - _GRIP - 3)
        self._grip.raise_()

    def mousePressEvent(self, event) -> None:
        # labels and the scroll area ignore presses, so a click on any non-button area lands here
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self._moved = True
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = None

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self._bar.color, 1))  # 1 px frame in the title bar colour
        painter.setBrush(QColor("#1f1f1f"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), _RADIUS, _RADIUS)
