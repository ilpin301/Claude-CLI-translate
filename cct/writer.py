"""Write / Paste window: a normal, always-on-top window with an input pane and a translation pane.

Layout (from the design sketch): left pane = what you type or paste (source language, size, Copy),
right pane = the translation (Copy, size, target language), a Translate button between the panes
(also Ctrl+Enter in the input). Nothing is sent anywhere until that button is pressed.
The window never talks to the network itself: it emits `request(req_id, text, source, target)` and
the app answers with show_result / show_error (same req_id). Answers for older requests are dropped.
Copy buttons are explicit clipboard writes, like the popup's.
"""
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPolygonF, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from . import config, settings

BLUE = "#2b79c2"
_CSS = """
QWidget#writer {background:#1c1c1c;}
QPlainTextEdit {background:#1c1c1c; color:#eaeaea; border:1px solid #7c7c7c; border-radius:12px; padding:8px;
                selection-background-color:#2b79c2;}
QComboBox, QPushButton#pill {color:%(blue)s; background:transparent; border:2px solid %(blue)s;
                border-radius:12px; padding:3px 12px; min-height:22px;}
QComboBox:hover, QPushButton#pill:hover {background:#24303d;}
QComboBox::drop-down {border:none; width:20px;}
QComboBox QAbstractItemView {background:#1c1c1c; color:%(blue)s; selection-background-color:#24303d;
                             selection-color:#ffffff; border:1px solid %(blue)s; outline:0;}
QPushButton#retry {color:#ddd; background:#333; border:none; border-radius:4px; padding:2px 10px;}
QPushButton#retry:hover {background:#444;}
QLabel#status {color:#9aa0a6;}
QLabel#status[error="true"] {color:#e57373;}
""" % {"blue": BLUE}


class TranslateButton(QPushButton):
    """The sketch's centre icon (two blocky arrows joined by a bar): "translate the left text into the right language"."""

    _LEFT = ((0, 23.6), (18, 11.8), (36, 0), (36, 23.6), (36, 47.2), (18, 35.4))
    _RIGHT = ((83.3, 23.6), (65.3, 11.8), (47.4, 0), (47.4, 23.6), (47.4, 47.2), (65.3, 35.4))
    _BAR = QRectF(29.6, 17.8, 26, 11.6)

    def __init__(self):
        super().__init__()
        self.setFixedSize(52, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Translate (Ctrl+Enter)")
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#4a9be0" if self.underMouse() else BLUE))
        scale = min((self.width() - 4) / 83.3, (self.height() - 4) / 47.2)
        painter.translate((self.width() - 83.3 * scale) / 2, (self.height() - 47.2 * scale) / 2)
        painter.scale(scale, scale)
        for pts in (self._LEFT, self._RIGHT):
            path = QPainterPath()
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
            painter.drawPath(path)
        painter.drawRect(self._BAR)


class WriterWindow(QWidget):
    request = Signal(int, str, str, str)  # req_id, text, source ("auto" or code), target
    settings_changed = Signal()  # the user picked a language / size: the app should save the settings

    def __init__(self, opts: dict):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setObjectName("writer")
        self.setWindowTitle("Claude CLI Translate - Write / Paste")
        self.setStyleSheet(_CSS)
        self.resize(960, 540)
        self.setMinimumSize(560, 320)
        self.opts = opts  # the app's live settings dict; this window edits only its writer_* keys
        self._req_id = 0
        self._output = ""
        self._retry_ok = False

        self._src_lang = self._lang_combo(auto=True)
        self._dst_lang = self._lang_combo(auto=False)
        self._src_size = self._size_combo()
        self._dst_size = self._size_combo()
        self._src_copy = self._pill("Copy")
        self._dst_copy = self._pill("Copy")
        self._go = TranslateButton()

        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Type or paste text here...")
        self._out = QPlainTextEdit()
        self._out.setReadOnly(True)
        self._out.setPlaceholderText("Translation")

        self._status = QLabel()
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        self._retry = QPushButton("Retry")
        self._retry.setObjectName("retry")
        self._retry.setCursor(Qt.PointingHandCursor)
        self._retry.setVisible(False)

        left_top = QHBoxLayout()
        left_top.addWidget(self._src_lang)
        left_top.addWidget(self._src_size)
        left_top.addStretch(1)
        left_top.addWidget(self._src_copy)
        right_top = QHBoxLayout()
        right_top.addWidget(self._dst_copy)
        right_top.addStretch(1)
        right_top.addWidget(self._dst_size)
        right_top.addWidget(self._dst_lang)
        left = QVBoxLayout()
        left.addLayout(left_top)
        left.addWidget(self._input, 1)
        right = QVBoxLayout()
        right.addLayout(right_top)
        right.addWidget(self._out, 1)
        mid = QVBoxLayout()
        mid.addWidget(self._go, 0, Qt.AlignTop)
        mid.addStretch(1)
        panes = QHBoxLayout()
        panes.addLayout(left, 1)
        panes.addLayout(mid)
        panes.addLayout(right, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(self._status, 1)
        bottom.addWidget(self._retry)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(8)
        root.addLayout(panes, 1)
        root.addLayout(bottom)

        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self._reset_copy_labels)

        self.apply_options()
        self._src_lang.currentIndexChanged.connect(self._on_lang_changed)
        self._dst_lang.currentIndexChanged.connect(self._on_lang_changed)
        self._src_size.currentIndexChanged.connect(self._on_size_changed)
        self._dst_size.currentIndexChanged.connect(self._on_size_changed)
        self._go.clicked.connect(self._send)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(keys), self._input)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(self._send)
        self._src_copy.clicked.connect(lambda: self._copy(self._input.toPlainText(), self._src_copy))
        self._dst_copy.clicked.connect(lambda: self._copy(self._output, self._dst_copy))
        self._retry.clicked.connect(self._send)

    # ---- construction helpers ----

    @staticmethod
    def _pill(text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("pill")
        btn.setMinimumWidth(84)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        return btn

    @staticmethod
    def _lang_combo(auto: bool) -> QComboBox:
        combo = QComboBox()
        if auto:
            combo.addItem("Auto detect", settings.AUTO_LANG)
        for code, name in settings.LANGUAGES:
            combo.addItem(name, code)
        combo.setMinimumContentsLength(12)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        return combo

    @staticmethod
    def _size_combo() -> QComboBox:
        combo = QComboBox()
        for px, label in settings.FONT_SIZES:
            combo.addItem(label, px)
        return combo

    # ---- public API ----

    def apply_options(self) -> None:
        """Push the stored writer_* options into the controls (no signals, no request)."""
        for combo, key in ((self._src_lang, "writer_src"), (self._dst_lang, "writer_dst"),
                           (self._src_size, "writer_font_in"), (self._dst_size, "writer_font_out")):
            combo.blockSignals(True)
            idx = combo.findData(self.opts[key])
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)
        self._apply_fonts()

    def present(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def contains_physical(self, x: int, y: int) -> bool:
        from . import winutil
        from .geometry import point_in_rect
        return self.isVisible() and point_in_rect(x, y, winutil.window_rect(int(self.winId())))

    def show_result(self, req_id: int, result) -> None:
        if req_id != self._req_id:
            return
        detected = result.detected_lang or ""
        self._output = result.text
        self._out.setPlainText(result.text)
        notes = []
        if self.opts["writer_src"] == settings.AUTO_LANG and detected:
            notes.append("Detected: %s" % detected)
        if result.same_lang:
            notes.append("Source and target language are the same.")
        if len(self._input.toPlainText()) > config.MAX_CHARS:
            notes.append("Only the first %d characters are translated." % config.MAX_CHARS)
        self._set_status("  ·  ".join(notes), retry=False)

    def show_error(self, req_id: int, message: str, retryable: bool) -> None:
        if req_id != self._req_id:
            return
        self._set_status(message, error=True, retry=retryable)

    @property
    def current_id(self) -> int:
        return self._req_id

    # ---- internals ----

    def _set_status(self, text: str, error: bool = False, retry: bool = False) -> None:
        self._status.setProperty("error", error)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        self._status.setText(text)
        self._retry.setVisible(retry)

    def _apply_fonts(self) -> None:
        for edit, key in ((self._input, "writer_font_in"), (self._out, "writer_font_out")):
            font = QFont("Segoe UI")
            font.setPixelSize(self.opts[key])
            edit.setFont(font)

    def _on_lang_changed(self) -> None:
        self.opts["writer_src"] = self._src_lang.currentData()
        self.opts["writer_dst"] = self._dst_lang.currentData()
        self.settings_changed.emit()

    def _on_size_changed(self) -> None:
        self.opts["writer_font_in"] = self._src_size.currentData()
        self.opts["writer_font_out"] = self._dst_size.currentData()
        self._apply_fonts()
        self.settings_changed.emit()

    def _send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            self._set_status("Nothing to translate: type or paste some text first.")
            return
        self._req_id += 1
        self._set_status("Translating...")
        self.request.emit(self._req_id, text[:config.MAX_CHARS], self.opts["writer_src"], self.opts["writer_dst"])

    def _copy(self, text: str, button: QPushButton) -> None:
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._reset_copy_labels()
        button.setText("Copied")
        self._flash.start(1200)

    def _reset_copy_labels(self) -> None:
        self._src_copy.setText("Copy")
        self._dst_copy.setText("Copy")
