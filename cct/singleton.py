"""Single instance via a named mutex (per user session)."""
import ctypes
from ctypes import wintypes

MUTEX_NAME = "Local\\ClaudeCliTranslate.SingleInstance"
ERROR_ALREADY_EXISTS = 183

_handle = None  # kept for the process lifetime; Windows releases it on exit


def acquire() -> bool:
    """True if this is the first instance. A mutex we cannot create at all is treated as 'first'."""
    global _handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _handle = handle
    return True
