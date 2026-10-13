"""Low-level mouse hook on a dedicated thread with its own message loop.

The callback only counts events and queues left-button events; it never logs,
never touches Qt and always returns through CallNextHookEx.
"""
import ctypes
import logging
import queue
import threading
from ctypes import wintypes

log = logging.getLogger("cct.hook")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_USER = 0x0400
WM_APP = 0x8000
MSG_REINSTALL = WM_APP + 1
MSG_QUIT = WM_APP + 2
VK_SHIFT = 0x10
PM_NOREMOVE = 0


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class MouseHook:
    def __init__(self):
        self.events = queue.SimpleQueue()  # (msg, x, y, tick_ms, shift_down)
        self.event_count = 0  # every mouse message seen, used by the watchdog
        self.installed = False
        self._hook = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._cb = HOOKPROC(self._proc)  # keep a reference so it is never collected
        self._thread = threading.Thread(target=self._run, name="cct-hook", daemon=True)

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(5) or not self.installed:
            raise RuntimeError("mouse hook could not be installed")

    def request_reinstall(self) -> None:
        user32.PostThreadMessageW(self._thread_id, MSG_REINSTALL, 0, 0)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, MSG_QUIT, 0, 0)
        self._thread.join(2)

    def _proc(self, n_code, w_param, l_param):
        try:
            if n_code >= 0:
                self.event_count += 1
                if w_param == WM_LBUTTONDOWN or w_param == WM_LBUTTONUP:
                    info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                    self.events.put_nowait((int(w_param), info.pt.x, info.pt.y, info.time, shift))
        except Exception:  # a hook callback must never raise
            pass
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def _install(self) -> None:
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._cb, kernel32.GetModuleHandleW(None), 0)
        self.installed = bool(self._hook)
        if not self.installed:
            log.error("SetWindowsHookExW failed, error %s", ctypes.get_last_error())

    def _uninstall(self) -> None:
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        self.installed = False

    def _run(self) -> None:
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, WM_USER, WM_USER, PM_NOREMOVE)  # create the thread queue
        self._thread_id = kernel32.GetCurrentThreadId()
        self._install()
        self._ready.set()
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            if msg.message == MSG_QUIT:
                break
            if msg.message == MSG_REINSTALL:
                log.warning("reinstalling mouse hook on the hook thread")
                self._uninstall()
                self._install()
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._uninstall()
