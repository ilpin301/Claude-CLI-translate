"""Non-activating translation popup (dark rounded panel), placed in physical pixels.

UNTESTED on a real Windows UI: layout sizing, DPI handling and non-activating mouse behaviour
have only been written from the icon.py pattern, never run.

Same window flags / extended styles as icon.py (helpers imported from there). Coordinates in/out are
physical pixels; the only physical -> Qt logical conversion is the size computed in _place().
The copy button is the only clipboard write in the app and happens only on an explicit click.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from . import config, settings, winutil
from .geometry import clamp_rect, point_in_rect
from .icon import (GWL_EXSTYLE, HWND_TOPMOST, SWP_NOACTIVATE, SWP_SHOWWINDOW, WS_EX_NOACTIVATE,
                   WS_EX_TOOLWINDOW, user32)

_MARGIN = 10
_BTN_CSS = ("QPushButton{color:#ddd;background:#333;border:none;border-radius:4px;padding:2px 8px;}"
            "QPushButton:hover{background:#444;}")


class PopupWindow(QWidget):
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

        self._header = QLabel()
        self._header.setStyleSheet("color:#9aa0a6;")
        self._copy = QPushButton("Copy")
        self._close = QPushButton("✕")
        for btn in (self._copy, self._close):
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setStyleSheet(_BTN_CSS)
            btn.setCursor(Qt.PointingHandCursor)
        self._copy.clicked.connect(self._on_copy)
        self._close.clicked.connect(self.hide_popup)
        top = QHBoxLayout()
        top.addWidget(self._header, 1)
        top.addWidget(self._copy)
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

        lay = QVBoxLayout(self)
        lay.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        lay.setSpacing(6)
        lay.addLayout(top)
        lay.addWidget(self._scroll)
        lay.addWidget(self._note)

        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: self._copy.setText("Copy"))
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
        self.setFixedWidth(self._width)

    def show_loading(self, px: int, py: int, target: str) -> None:
        self._anchor = (px, py)
        self._translation = ""
        self._set_content("auto → %s" % target, "Translating…", "", copy=False)

    def show_result(self, result, truncated: bool, target: str) -> None:
        notes = []
        if result.same_lang:
            notes.append("Source and target language are the same.")
        if truncated:
            notes.append("Text was truncated to %d characters." % config.MAX_CHARS)
        self._translation = result.text
        self._set_content("%s → %s" % (result.detected_lang or "auto", target),
                          result.text, " ".join(notes), copy=True)

    def show_error(self, msg: str) -> None:
        self._translation = ""
        self._set_content("Translation failed", msg, "", copy=False)

    def hide_popup(self) -> None:
        self._copy_timer.stop()
        self.hide()

    def contains_physical(self, x: int, y: int) -> bool:
        return self.isVisible() and point_in_rect(x, y, winutil.window_rect(self._hwnd()))

    # ---- internals ----

    def _hwnd(self) -> int:
        return int(self.winId())

    def _apply_ex_style(self) -> None:
        if self._styled:
            return
        hwnd = self._hwnd()
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        self._styled = True

    def _set_content(self, header: str, body: str, note: str, copy: bool) -> None:
        self._header.setText(header)
        self._copy.setVisible(copy)
        self._copy.setText("Copy")
        self._note.setText(note)
        self._note.setVisible(bool(note))
        self._body.setText(body)
        inner = self._width - 2 * _MARGIN
        body_h = self._body.heightForWidth(inner - 14)  # 14: scrollbar allowance
        self._scroll.setFixedHeight(min(max(body_h, 20) + 4, self._max_height))
        self.layout().activate()
        self.resize(self._width, self.layout().sizeHint().height())
        self._place()

    def _place(self) -> None:
        px, py = self._anchor
        work, scale = winutil.monitor_at(px, py)
        # the one logical -> physical conversion (mirrors icon.py)
        w = round(self.width() * scale)
        h = round(self.height() * scale)
        x, y = clamp_rect(px, py + round(config.ICON_OFFSET * scale), w, h, work)
        self.show()
        self._apply_ex_style()
        user32.SetWindowPos(self._hwnd(), HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def _on_copy(self) -> None:
        if not self._translation:
            return
        QApplication.clipboard().setText(self._translation)
        self._copy.setText("Copied")
        self._copy_timer.start(1200)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1f1f1f"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
