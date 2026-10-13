"""Phase 4 helper: check whether a terminal host exposes a selection through UIA.

Run from the project folder in ANY terminal:  python tools/probe_host.py
You get 8 seconds to switch to the terminal under test (conhost, OpenConsole, VS Code, elevated, ...)
and Shift+drag some text there. The script then reports the foreground exe, window class, whether UIA
returned a selection and how long it is. It never prints the selected text, only its length.
"""
import sys

sys.coinit_flags = 0  # MTA, must precede comtypes (see PLAN.md, Phase 0 result 5)

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32")
user32.GetForegroundWindow.restype = wintypes.HWND

UIA_TEXT_PATTERN_ID = 10014


def main() -> None:
    for left in range(8, 0, -1):
        print("switch now and Shift+drag some text... %d" % left, end="\r", flush=True)
        time.sleep(1)
    print(" " * 50)
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    sys.path.insert(0, ".")
    from cct import winutil
    print("foreground exe  :", winutil.foreground_exe() or "(unknown - probably elevated)")
    print("window class    :", buf.value)
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA
    uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
    element = uia.GetFocusedElement()
    print("focused element :", element.CurrentClassName or "(no class)", "/", element.CurrentName[:40])
    pattern = element.GetCurrentPattern(UIA_TEXT_PATTERN_ID)
    if not pattern:
        print("RESULT: no TextPattern -> this host cannot be read through UIA")
        return
    ranges = pattern.QueryInterface(UIA.IUIAutomationTextPattern).GetSelection()
    text = "\n".join(ranges.GetElement(i).GetText(-1) for i in range(ranges.Length))
    print("RESULT: TextPattern ok, %d selection range(s), %d chars" % (ranges.Length, len(text)))
    if not text:
        print("        (empty: either nothing was selected or the host does not report selections)")


if __name__ == "__main__":
    main()
