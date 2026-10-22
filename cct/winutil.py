"""Small Win32 helpers; every coordinate is a physical pixel."""
import ctypes
import os
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")
shcore = ctypes.WinDLL("shcore")

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
shcore.GetDpiForMonitor.argtypes = [
    wintypes.HMONITOR, ctypes.c_int, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
shcore.GetDpiForMonitor.restype = ctypes.c_long

user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.GetClipboardOwner.restype = wintypes.HWND
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.restype = ctypes.c_size_t

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
CF_UNICODETEXT = 13
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def window_exe(hwnd) -> str:
    """Lower-case exe file name of the process owning hwnd, or '' if unknown."""
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def foreground_exe() -> str:
    return window_exe(user32.GetForegroundWindow())


def window_class(hwnd) -> str:
    """Lower-case window class name, or '' if unknown."""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    if user32.GetClassNameW(hwnd, buf, 256):
        return buf.value.lower()
    return ""


def foreground_window():
    """(exe, window class), both lower-case, of the foreground window."""
    hwnd = user32.GetForegroundWindow()
    return window_exe(hwnd), window_class(hwnd)


def window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def monitor_at(x: int, y: int):
    """((left, top, right, bottom) work area, dpi scale) of the monitor nearest to the physical point."""
    hmon = user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    work = info.rcWork
    scale = 1.0
    try:
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            scale = dpi_x.value / 96.0
    except OSError:
        pass
    return (work.left, work.top, work.right, work.bottom), scale


def clipboard_seq() -> int:
    """Clipboard change counter; it grows with every write by any application."""
    return int(user32.GetClipboardSequenceNumber())


def clipboard_owner_exe() -> str:
    """Exe of the process that last wrote the clipboard, '' when it has no owner window."""
    return window_exe(user32.GetClipboardOwner())


def clipboard_text(max_chars: int) -> str:
    """Unicode text on the clipboard ('' if none, busy, or marked private by its writer). Read-only."""
    private = user32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
    if private and user32.IsClipboardFormatAvailable(private):
        return ""  # password managers set this marker: never read it
    for _attempt in range(5):  # another process may hold the clipboard for a moment
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            chars = min(kernel32.GlobalSize(handle) // 2, max_chars + 1)
            return ctypes.wstring_at(ptr, chars).split("\0", 1)[0][:max_chars]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
