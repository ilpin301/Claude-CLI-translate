"""Phase P2 app: mouse hook + Shift gating -> UIA read -> normalise -> icons -> click -> translate -> popup.

Flow: a mouse-drag trigger (any drag, or Shift+drag only, per the "trigger" setting) in an allowlisted window asks the UIA worker (cct.uia) for the selection;
a non-empty result is normalised and the icons appear (Google, and GLM unless switched off). Nothing
is translated or sent until an icon is clicked; then the stored text is translated on that engine's
worker thread and the popup shows the result. The other icon stays until it is clicked or dismissed. Worker threads reach the GUI thread only through Qt signals. A mouse-down outside the popup
(and not on the icon) closes it, a new selection closes it, a mouse-down inside it is not a selection.
"""
from . import uia  # noqa: F401  (must come first: sets sys.coinit_flags = 0 before PySide6/comtypes)

import logging
import queue
import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMenu, QSystemTrayIcon

from . import autostart, config, settings, singleton, winutil
from .gating import WM_LBUTTONDOWN, WM_LBUTTONUP, Gate
from .glm import GlmTranslator
from .icon import BAR_COLORS, GLM, GOOGLE, IconBar
from .normalize import normalize
from .popup import PopupWindow
from .translate import GoogleTranslator, TranslateError
from .winhook import MouseHook
from .writer import WriterWindow

log = logging.getLogger("cct")


def _tray_pixmap() -> QPixmap:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#2d6cdf"))
    painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 7, 7)
    painter.setPen(QColor("white"))
    font = QFont("Segoe UI")
    font.setPixelSize(24)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "A")
    painter.end()
    return pixmap


class Bridge(QObject):
    """Carries results from worker threads to the GUI thread (queued signal delivery)."""
    selection = Signal(int, object)  # request id, text or None
    translated = Signal(int, object, str, bool)  # translation id, TranslationResult or None, error message, retryable
    written = Signal(int, object, str, bool)  # same, for the Write / Paste window


class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.gate = Gate(True, config.MIN_DRAG_PX)  # require_shift is set from the settings below
        self.hook = MouseHook()
        self.icon = IconBar()
        for engine, win in self.icon.windows.items():
            win.clicked.connect(lambda e=engine: self.on_icon_clicked(e))
        self.settings = settings.load()
        self.gate.require_shift = self.settings["trigger"] == "shift"
        self.popup = PopupWindow(self.settings["font_px"])
        self.bridge = Bridge()
        self.bridge.selection.connect(self.on_selection)
        self.bridge.translated.connect(self.on_translated)
        self.popup.retry_requested.connect(self.on_retry)
        self.writer = WriterWindow(self.settings)
        self.writer.request.connect(self.on_writer_request)
        self.writer.settings_changed.connect(self._save)
        self.bridge.written.connect(self.on_written)
        self.worker = uia.SelectionWorker(self.bridge.selection.emit, self.window_allowed)
        self.translator = GoogleTranslator(self.settings["proxy_mode"])  # also used by the Write / Paste window
        self.translators = {
            GOOGLE: self.translator,
            GLM: GlmTranslator(self.glm_key, self.settings["proxy_mode"], self.settings["glm_model"],
                               self.glm_base_url())}
        # one worker per engine, so a slow Google retry never delays a GLM click (and vice versa)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cct-translate")
        self.glm_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cct-glm")
        self._req_id = 0  # bumped by every new selection and every outside mouse-down; stale reads are dropped
        self._tr_id = 0  # bumped by every popup translation (and with _req_id); stale translations are dropped
        self._engine = GOOGLE  # engine of the popup's current translation
        self._trigger_pt = (0, 0)
        self._text = None
        self._truncated = False
        self._result_lang = self.settings["target_lang"]
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
        self.tray.setToolTip("Claude CLI Translate - select text with the mouse, then click the icon")
        menu = QMenu()
        self._enable_action = QAction("Enabled", menu)
        self._enable_action.setCheckable(True)
        self._enable_action.setChecked(self.settings["enabled"])
        self._enable_action.toggled.connect(self.set_enabled)
        menu.addAction(self._enable_action)
        lang_menu = menu.addMenu("Target language")
        self._lang_group = self._radio_menu(
            lang_menu, [(code, "%s (%s)" % (name, code)) for code, name in settings.LANGUAGES],
            self.settings["target_lang"], self.set_target_lang)
        write_action = QAction("Write / Paste...", menu)
        write_action.triggered.connect(self.writer.present)
        menu.addAction(write_action)
        settings_menu = menu.addMenu("Settings")
        scope_menu = settings_menu.addMenu("Scope")
        self._scope_group = self._radio_menu(
            scope_menu, [("terminals", "Terminals only (allowlist)"), ("all", "All applications")],
            self.settings["scope"], self.set_scope)
        trigger_menu = settings_menu.addMenu("Trigger")
        self._trigger_group = self._radio_menu(
            trigger_menu, [("any", "Any mouse drag"), ("shift", "Shift+drag only")],
            self.settings["trigger"], self.set_trigger)
        font_menu = settings_menu.addMenu("Font size")
        self._font_group = self._radio_menu(
            font_menu, [(px, "%s (%d px)" % (label, px)) for px, label in settings.FONT_SIZES],
            self.settings["font_px"], self.set_font)
        self._autostart_action = QAction("Start with Windows", settings_menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(autostart.is_enabled())
        self._autostart_action.toggled.connect(self.set_autostart)
        settings_menu.addAction(self._autostart_action)
        glm_menu = settings_menu.addMenu("GLM")
        self._glm_icon_action = QAction("Show GLM icon", glm_menu)
        self._glm_icon_action.setCheckable(True)
        self._glm_icon_action.setChecked(self.settings["glm_icon"])
        self._glm_icon_action.toggled.connect(self.set_glm_icon)
        glm_menu.addAction(self._glm_icon_action)
        model_menu = glm_menu.addMenu("Model")
        self._model_group = self._radio_menu(model_menu, list(settings.GLM_MODELS),
                                             self.settings["glm_model"], self.set_glm_model)
        self._key_status = QAction("", glm_menu)
        self._key_status.setEnabled(False)
        glm_menu.addAction(self._key_status)
        key_action = QAction("Set API key...", glm_menu)
        key_action.triggered.connect(self.ask_glm_key)
        glm_menu.addAction(key_action)
        self._remove_key_action = QAction("Remove saved API key", glm_menu)
        self._remove_key_action.triggered.connect(self.remove_glm_key)
        glm_menu.addAction(self._remove_key_action)
        glm_menu.aboutToShow.connect(self._refresh_glm_menu)
        self._refresh_glm_menu()
        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self._menu = menu

    @staticmethod
    def _radio_menu(menu, entries, current, callback):
        group = QActionGroup(menu)
        group.setExclusive(True)
        for value, label in entries:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(value == current)
            action.triggered.connect(lambda _checked=False, v=value: callback(v))
            group.addAction(action)
            menu.addAction(action)
        return group

    def _save(self) -> None:
        settings.save(self.settings)

    def set_enabled(self, enabled: bool) -> None:
        self.settings["enabled"] = bool(enabled)
        self._req_id += 1  # drop any pending read / translation
        self._tr_id += 1
        self.icon.hide_icon()
        if not enabled:
            self.popup.hide_popup()
        self._save()
        log.info("enabled=%s", enabled)

    def set_target_lang(self, code: str) -> None:
        self.settings["target_lang"] = settings.valid_lang(code)
        self._save()
        log.info("target language set to %s", self.settings["target_lang"])

    def set_scope(self, scope: str) -> None:
        self.settings["scope"] = scope if scope in settings.SCOPES else "terminals"
        self._save()
        log.info("scope set to %s", self.settings["scope"])

    def set_trigger(self, trigger: str) -> None:
        self.settings["trigger"] = trigger if trigger in settings.TRIGGERS else "any"
        self.gate.require_shift = self.settings["trigger"] == "shift"
        self.gate.reset()
        self._save()
        log.info("trigger set to %s", self.settings["trigger"])

    def set_autostart(self, enabled: bool) -> None:
        if not autostart.set_enabled(bool(enabled)):
            actual = autostart.is_enabled()  # registry write failed: show the real state again
            self._autostart_action.blockSignals(True)
            self._autostart_action.setChecked(actual)
            self._autostart_action.blockSignals(False)
            self.tray.showMessage("Claude CLI Translate", "Could not change the start-up setting.")

    def glm_key(self) -> str:
        """Saved key first, else a GLM key from the environment (see settings.glm_env_key). Never logged."""
        return self.settings["glm_api_key"] or settings.glm_env_key()[1]

    def glm_base_url(self) -> str:
        """The settings.json value when the user changed it, else the region implied by the environment."""
        url = self.settings["glm_base_url"]
        return settings.glm_env_base_url() if url == settings.DEFAULT_GLM_BASE_URL else url

    def _refresh_glm_menu(self) -> None:
        if self.settings["glm_api_key"]:
            status = "API key: saved"
        elif settings.glm_env_key()[0]:
            status = "API key: from %s" % settings.glm_env_key()[0]
        else:
            status = "API key: not set"
        self._key_status.setText(status)
        self._remove_key_action.setEnabled(bool(self.settings["glm_api_key"]))

    def set_glm_icon(self, enabled: bool) -> None:
        self.settings["glm_icon"] = bool(enabled)
        if not enabled:
            self.icon.hide_icon(GLM)
        self._save()

    def set_glm_model(self, model: str) -> None:
        self.settings["glm_model"] = model
        self.translators[GLM].model = model
        self._save()
        log.info("glm model set to %s", model)

    def ask_glm_key(self) -> None:
        dialog = QInputDialog()
        dialog.setWindowTitle("GLM API key")
        dialog.setLabelText("Paste your Z.ai (GLM) API key.\n"
                            "It is stored in your settings.json (or set the ZAI_API_KEY variable instead).")
        dialog.setTextEchoMode(QLineEdit.Password)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if dialog.exec() and dialog.textValue().strip():
            self.settings["glm_api_key"] = dialog.textValue().strip()[:settings.MAX_KEY_CHARS]
            self._save()
            self._refresh_glm_menu()

    def remove_glm_key(self) -> None:
        self.settings["glm_api_key"] = ""
        self._save()
        self._refresh_glm_menu()

    def window_allowed(self, exe: str, window_class: str) -> bool:
        return settings.window_allowed(exe, window_class, self.settings)

    def start(self) -> None:
        self.worker.start()
        self.hook.start()
        self.poll.start()
        self.watchdog.start()
        self.tray.show()
        if not self.settings["first_run_done"]:
            self.tray.showMessage("Claude CLI Translate",
                                  "Select text with the mouse, then click the icon to translate.")
            self.settings["first_run_done"] = True
            settings.save(self.settings)
        log.info("started; scope=%s allowlist=%s lang=%s proxy_mode=%s enabled=%s", self.settings["scope"],
                 self.settings["allowlist"], self.settings["target_lang"], self.settings["proxy_mode"],
                 self.settings["enabled"])

    def quit(self) -> None:
        log.info("quit requested")
        self.poll.stop()
        self.watchdog.stop()
        self.icon.hide_icon()
        self.popup.hide_popup()
        self.writer.close()
        self.worker.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.glm_executor.shutdown(wait=False, cancel_futures=True)
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
            if (self.popup.contains_physical(x, y) or self.icon.contains_physical(x, y)
                    or self.writer.contains_physical(x, y)):
                self._ignore_up = True  # the popup / icon / writer window handle their own clicks
                return
            self._ignore_up = False
            self._req_id += 1  # invalidates any pending read or translation
            self._tr_id += 1
            self.popup.hide_popup()
        elif msg == WM_LBUTTONUP and self._ignore_up:
            self._ignore_up = False
            self.gate.reset()
            return
        trigger = self.gate.feed(ev)
        if trigger is None:
            return
        exe, cls = winutil.foreground_window()
        if not self.window_allowed(exe, cls):
            log.info("trigger ignored, foreground exe %r class %r not allowed (scope=%s, enabled=%s)",
                     exe, cls, self.settings["scope"], self.settings["enabled"])
            return
        log.info("trigger exe=%s class=%s drag=%.0fpx", exe, cls, trigger.drag_px)
        self._req_id += 1
        self._tr_id += 1
        self._trigger_pt = (trigger.x, trigger.y)
        self._text = None
        self.icon.hide_icon()  # the old icon belongs to the previous selection; a new one appears if this read succeeds
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
        engines = [GOOGLE, GLM] if self.settings["glm_icon"] else [GOOGLE]
        self.icon.show_near(*self._trigger_pt, engines)

    def on_icon_clicked(self, engine: str) -> None:
        log.info("icon clicked: %s", engine)
        self.icon.hide_icon(engine)  # only the clicked icon goes away; the other one stays until it is used
        if not self._text:
            return
        self._engine = engine
        self._result_lang = self.settings["target_lang"]
        self._start_translation()

    def on_retry(self) -> None:
        if not self._text or not self.popup.isVisible():
            return
        log.info("retry clicked")
        self._start_translation()

    def _start_translation(self) -> None:
        self._tr_id += 1  # an answer still on its way from the other engine is now stale
        name = "Google" if self._engine == GOOGLE else self._glm_model_name()
        self.popup.show_loading(*self._trigger_pt, self._result_lang, name, BAR_COLORS[self._engine])
        pool = self.executor if self._engine == GOOGLE else self.glm_executor
        pool.submit(self._translate, self._tr_id, self._engine, self._text, self._result_lang)

    def _glm_model_name(self) -> str:
        model = self.settings["glm_model"]
        return dict(settings.GLM_MODELS).get(model, model).split(" (")[0]

    def _translate(self, tr_id: int, engine: str, text: str, lang: str) -> None:  # runs on an engine's worker thread
        try:
            result = self.translators[engine].translate(text, lang)
        except TranslateError as exc:
            self.bridge.translated.emit(tr_id, None, str(exc), exc.retryable)
            return
        except Exception:
            log.exception("translate failed")
            self.bridge.translated.emit(tr_id, None, "Unexpected translation error.", True)
            return
        self.bridge.translated.emit(tr_id, result, "", False)

    def on_translated(self, tr_id: int, result, error: str, retryable: bool) -> None:
        if tr_id != self._tr_id or not self.popup.isVisible():
            return
        if result is None:
            self.popup.show_error(error, retryable)
        else:
            self.popup.show_result(result, self._truncated, self._result_lang)

    def on_writer_request(self, req_id: int, text: str, source: str, target: str) -> None:
        self.executor.submit(self._translate_writer, req_id, text, source, target)

    def _translate_writer(self, req_id: int, text: str, source: str, target: str) -> None:  # translate thread
        if req_id != self.writer.current_id:
            return  # the user kept typing; a newer request follows
        try:
            result = self.translator.translate(text, target, source)
        except TranslateError as exc:
            self.bridge.written.emit(req_id, None, str(exc), exc.retryable)
            return
        except Exception:
            log.exception("writer translate failed")
            self.bridge.written.emit(req_id, None, "Unexpected translation error.", True)
            return
        self.bridge.written.emit(req_id, result, "", False)

    def on_written(self, req_id: int, result, error: str, retryable: bool) -> None:
        if result is None:
            self.writer.show_error(req_id, error, retryable)
        else:
            self.writer.show_result(req_id, result)

    def set_font(self, px: int) -> None:
        px = settings.clamp_font(px)
        self.settings["font_px"] = px
        self.popup.set_font_px(px)
        settings.save(self.settings)
        log.info("popup font size set to %d px", px)

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
    if not singleton.acquire():
        return  # another instance is already running in this session
    logging.getLogger().addHandler(logging.NullHandler())  # nothing is written to disk; also silences logging's stderr fallback
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    app = App(qapp)
    app.start()
    sys.exit(qapp.exec())
