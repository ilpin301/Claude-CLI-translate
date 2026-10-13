"""Phase P2 app: mouse hook + Shift gating -> UIA read -> normalise -> icon -> click -> translate -> popup.

Flow: a Shift+drag trigger in an allowlisted window asks the UIA worker (cct.uia) for the selection;
a non-empty result is normalised and the icon appears. Nothing is translated or sent until the icon
is clicked; then the stored text is translated on a single worker thread and the popup shows the
result. Worker threads reach the GUI thread only through Qt signals. A mouse-down outside the popup
(and not on the icon) closes it, a new selection closes it, a mouse-down inside it is not a selection.
"""
from . import uia  # noqa: F401  (must come first: sets sys.coinit_flags = 0 before PySide6/comtypes)

import faulthandler
import logging
import logging.handlers
import os
import queue
import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config, winutil
from .gating import WM_LBUTTONDOWN, WM_LBUTTONUP, Gate
from .icon import IconWindow
from .normalize import normalize
from .popup import PopupWindow
from .translate import GoogleTranslator, TranslateError
from .winhook import MouseHook

log = logging.getLogger("cct")
LOG_DIR = os.path.join(os.environ.get("APPDATA", "."), "ClaudeCliTranslate")
_fault_file = None


def setup_logging() -> None:
    global _fault_file
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "cct.log"), maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    _fault_file = open(os.path.join(LOG_DIR, "cct-fault.log"), "a", encoding="utf-8")
    faulthandler.enable(_fault_file)

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("cct").critical("uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook


def _tray_pixmap() -> QPixmap:
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#2d6cdf"))
    return pixmap


class Bridge(QObject):
    """Carries results from worker threads to the GUI thread (queued signal delivery)."""
    selection = Signal(int, object)  # request id, text or None
    translated = Signal(int, object, str)  # request id, TranslationResult or None, error message


class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.gate = Gate(config.REQUIRE_SHIFT, config.MIN_DRAG_PX)
        self.hook = MouseHook()
        self.icon = IconWindow()
        self.icon.clicked.connect(self.on_icon_clicked)
        self.popup = PopupWindow()
        self.bridge = Bridge()
        self.bridge.selection.connect(self.on_selection)
        self.bridge.translated.connect(self.on_translated)
        self.worker = uia.SelectionWorker(self.bridge.selection.emit)
        self.translator = GoogleTranslator(config.PROXY_MODE)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cct-translate")
        self._req_id = 0  # bumped by every new selection and every outside mouse-down; stale results are dropped
        self._trigger_pt = (0, 0)
        self._text = None
        self._truncated = False
        self._ignore_up = False
        self._last_cursor = winutil.cursor_pos()
        self._last_count = 0
        self._stale = 0

        self.poll = QTimer()
        self.poll.setInterval(config.POLL_INTERVAL_MS)
        self.poll.timeout.connect(self.drain)
        self.watchdog = QTimer()
        self.watchdog.setInterval(config.WATCHDOG_INTERVAL_MS)
        self.watchdog.timeout.connect(self.check_hook)

        self.tray = QSystemTrayIcon(QIcon(_tray_pixmap()))
        self.tray.setToolTip("Claude CLI Translate - hold Shift while dragging to select")
        menu = QMenu()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self._menu = menu

    def start(self) -> None:
        self.worker.start()
        self.hook.start()
        self.poll.start()
        self.watchdog.start()
        self.tray.show()
        self.tray.showMessage("Claude CLI Translate", "Running. Hold Shift while dragging to select text.")
        log.info("started; allowlist=%s require_shift=%s", sorted(config.ALLOWLIST), config.REQUIRE_SHIFT)

    def quit(self) -> None:
        log.info("quit requested")
        self.poll.stop()
        self.watchdog.stop()
        self.icon.hide_icon()
        self.popup.hide_popup()
        self.worker.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.hook.stop()
        self.tray.hide()
        self.qapp.quit()

    def drain(self) -> None:
        while True:
            try:
                ev = self.hook.events.get_nowait()
            except queue.Empty:
                return
            self.handle(ev)

    def handle(self, ev) -> None:
        msg, x, y, _tick, _shift = ev
        if msg == WM_LBUTTONDOWN:
            if self.popup.contains_physical(x, y) or self.icon.contains_physical(x, y):
                self._ignore_up = True  # the popup / icon handle their own clicks
                return
            self._ignore_up = False
            self._req_id += 1  # invalidates any pending read or translation
            self.icon.hide_icon()
            self.popup.hide_popup()
        elif msg == WM_LBUTTONUP and self._ignore_up:
            self._ignore_up = False
            self.gate.reset()
            return
        trigger = self.gate.feed(ev)
        if trigger is None:
            return
        exe = winutil.foreground_exe()
        if exe not in config.ALLOWLIST:
            log.info("trigger ignored, foreground exe %r not allowlisted", exe)
            return
        log.info("trigger exe=%s drag=%.0fpx", exe, trigger.drag_px)
        self._req_id += 1
        self._trigger_pt = (trigger.x, trigger.y)
        self._text = None
        self.worker.request(self._req_id)

    def on_selection(self, req_id: int, text) -> None:
        if req_id != self._req_id:
            return
        norm, truncated = normalize(text or "", config.MAX_CHARS)
        if not norm:
            log.info("no usable selection (raw len=%d)", len(text or ""))
            return
        self._text, self._truncated = norm, truncated
        log.info("selection ready len=%d truncated=%s", len(norm), truncated)
        self.icon.show_near(*self._trigger_pt)

    def on_icon_clicked(self) -> None:
        log.info("icon clicked")
        self.icon.hide_icon()
        if not self._text:
            return
        self.popup.show_loading(*self._trigger_pt, config.TARGET_LANG)
        self.executor.submit(self._translate, self._req_id, self._text)

    def _translate(self, req_id: int, text: str) -> None:  # runs on the translate thread
        try:
            result = self.translator.translate(text, config.TARGET_LANG)
        except TranslateError as exc:
            self.bridge.translated.emit(req_id, None, str(exc))
            return
        except Exception:
            log.exception("translate failed")
            self.bridge.translated.emit(req_id, None, "Unexpected translation error (see log).")
            return
        self.bridge.translated.emit(req_id, result, "")

    def on_translated(self, req_id: int, result, error: str) -> None:
        if req_id != self._req_id or not self.popup.isVisible():
            return
        if result is None:
            self.popup.show_error(error)
        else:
            self.popup.show_result(result, self._truncated)

    def check_hook(self) -> None:
        cursor = winutil.cursor_pos()
        count = self.hook.event_count
        if cursor != self._last_cursor and count == self._last_count:
            self._stale += 1
        else:
            self._stale = 0
        self._last_cursor, self._last_count = cursor, count
        if self._stale >= config.WATCHDOG_STALE_TICKS:
            log.warning("hook silent while the cursor moves; requesting reinstall")
            self.hook.request_reinstall()
            self._stale = 0


def main() -> None:
    setup_logging()
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    app = App(qapp)
    app.start()
    sys.exit(qapp.exec())
