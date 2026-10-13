"""Phase P1 app: mouse hook + Shift gating + icon + minimal tray. Selection read/translation come later."""
import faulthandler
import logging
import logging.handlers
import os
import queue
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config, winutil
from .gating import WM_LBUTTONDOWN, WM_LBUTTONUP, Gate
from .icon import IconWindow
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


class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.gate = Gate(config.REQUIRE_SHIFT, config.MIN_DRAG_PX)
        self.hook = MouseHook()
        self.icon = IconWindow()
        self.icon.clicked.connect(self.on_icon_clicked)
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
            if self.icon.contains_physical(x, y):
                self._ignore_up = True  # the icon handles its own click
                return
            self._ignore_up = False
            self.icon.hide_icon()
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
        self.icon.show_near(trigger.x, trigger.y)

    def on_icon_clicked(self) -> None:
        log.info("icon clicked")
        self.icon.hide_icon()
        self.tray.showMessage("Claude CLI Translate", "Icon clicked (phase 1 placeholder: no translation yet).")

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
