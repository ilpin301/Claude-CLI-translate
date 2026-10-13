"""UIA selection read worker (Windows only).

UNTESTED in the real app on Windows UI: the read recipe is the one measured in the Phase 0 spike
(spike/p0_uia_spike.py), but the worker threading, the watchdog and the MTA ordering inside the
PySide6 app have not been exercised yet.

* Importing this module sets sys.coinit_flags = 0 (MTA). cct.app imports it before PySide6 so the
  flag is in place before comtypes is first imported; comtypes itself is only imported lazily ON the
  worker thread, so COM is initialised as MTA there and never on the Qt GUI thread.
* One daemon worker thread consumes requests (the newest request wins, older ones are dropped).
  Per request: wait until UIA_FIRST_DELAY_MS after the request time, read; if empty retry once at
  UIA_RETRY_DELAY_MS; still empty -> result None.
* Watchdog: Python threads cannot be cancelled. If a UIA call has been running longer than
  UIA_READ_TIMEOUT_MS when the next request arrives, the worker is flagged unhealthy, the request is
  answered with None immediately and no new work is queued until the stuck call returns. No second
  worker thread is ever spawned.
* on_result(request_id, text_or_None) is called from the worker thread (or, when unhealthy, from the
  requesting thread); it must be thread-safe, e.g. emit a Qt Signal. This module never imports Qt.
* Logs one line per read: latency, status, length. Never the text.
"""
import sys

sys.coinit_flags = 0  # COINIT_MULTITHREADED; must be set before comtypes is imported anywhere

import ctypes  # noqa: E402
import logging  # noqa: E402
import queue  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from . import config, winutil  # noqa: E402

log = logging.getLogger("cct.uia")

UIA_TEXT_PATTERN_ID = 10014
_APARTMENTS = {0: "STA", 1: "MTA", 2: "NA", 3: "MAINSTA"}


def _apartment_name() -> str:
    try:
        kind, qual = ctypes.c_int(), ctypes.c_int()
        hr = ctypes.windll.ole32.CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qual))
        if hr != 0:
            return "CoGetApartmentType failed hr=0x%08x" % (hr & 0xFFFFFFFF)
        return "%s (qualifier %d)" % (_APARTMENTS.get(kind.value, str(kind.value)), qual.value)
    except Exception as exc:  # diagnostics only
        return "unknown (%s)" % type(exc).__name__


class SelectionWorker:
    def __init__(self, on_result):
        self._on_result = on_result
        self._q = queue.Queue()
        self._latest = 0
        self._call_started = None  # monotonic time of the UIA call in flight, else None
        self._unhealthy = False
        self._uia = None
        self._UIA = None
        self._thread = threading.Thread(target=self._run, name="cct-uia", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._latest += 1
        self._q.put(None)

    def request(self, request_id: int, t0=None) -> None:
        """Ask for a read; t0 (time.monotonic) is the mouse-up time the delays are measured from."""
        t0 = time.monotonic() if t0 is None else t0
        started = self._call_started
        if started is not None and (time.monotonic() - started) * 1000 > config.UIA_READ_TIMEOUT_MS:
            if not self._unhealthy:
                log.warning("uia worker unhealthy: previous read stuck for >%d ms; skipping until it returns",
                            config.UIA_READ_TIMEOUT_MS)
            self._unhealthy = True
        if self._unhealthy:
            self._on_result(request_id, None)
            return
        self._latest = request_id
        self._q.put((request_id, t0))

    # ---- worker thread ----

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            while True:  # newest request wins
                try:
                    nxt = self._q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    return
                item = nxt
            try:
                self._handle(*item)
            except Exception:
                log.exception("uia worker request failed")
                self._deliver(item[0], None)

    def _deliver(self, request_id, text) -> None:
        if request_id == self._latest:
            self._on_result(request_id, text)

    def _wait_until(self, request_id, t0, delay_ms) -> bool:
        remaining = t0 + delay_ms / 1000.0 - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        return request_id == self._latest  # False: superseded

    def _handle(self, request_id, t0) -> None:
        for delay in (config.UIA_FIRST_DELAY_MS, config.UIA_RETRY_DELAY_MS):
            if not self._wait_until(request_id, t0, delay):
                return
            status, text = self._read_once()
            if text:
                self._deliver(request_id, text)
                return
            if status == "skipped":
                break
        self._deliver(request_id, None)

    def _read_once(self):
        started = time.monotonic()
        status, text = "error", ""
        try:
            exe = winutil.foreground_exe()  # re-verified right before the UIA call
            if exe not in config.ALLOWLIST:
                status = "skipped"
                return status, text
            self._call_started = time.monotonic()
            try:
                text = self._read_selection()
            finally:
                self._call_started = None
                if self._unhealthy:
                    self._unhealthy = False
                    log.warning("uia worker recovered: stuck read returned")
            status = "ok" if text else "empty"
        except Exception as exc:
            log.warning("uia read failed: %s: %s", type(exc).__name__, exc)
        finally:
            if status != "skipped":
                log.info("uia read status=%s len=%d ms=%d", status, len(text),
                         (time.monotonic() - started) * 1000)
        return status, text

    def _init_uia(self) -> None:
        import comtypes.client  # imported here, on the worker thread, after sys.coinit_flags = 0
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
        self._UIA = UIA
        self._uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)

    def _read_selection(self) -> str:
        if self._uia is None:
            try:
                self._init_uia()
                log.info("uia init ok; worker thread COM apartment: %s", _apartment_name())
            except Exception as exc:
                log.error("uia init failed: %s: %s; apartment: %s", type(exc).__name__, exc, _apartment_name())
                raise
        element = self._uia.GetFocusedElement()
        pattern = element.GetCurrentPattern(UIA_TEXT_PATTERN_ID)
        if not pattern:
            return ""
        ranges = pattern.QueryInterface(self._UIA.IUIAutomationTextPattern).GetSelection()
        return "\n".join(ranges.GetElement(i).GetText(-1) for i in range(ranges.Length))
