"""Read-only fallback for hosts that keep the selection to themselves (Claude Code's own mouse selection).

Claude Code copies what you drag-select to the clipboard within about 1.5 s, and Windows Terminal then has no
selection of its own for UIA to read. After a drag where UIA found nothing, the worker polls the clipboard
sequence number and accepts the text only when the clipboard changed after the mouse went down AND was written
by the terminal itself (not by another application) AND is not marked as private. The app never writes the
clipboard here and never keeps the text beyond the current selection.

Pure logic with injected Win32 calls, so it is unit-tested without Windows.
"""
import time

# Clipboard owners that count as "the terminal copied it" besides the foreground window's own process.
TERMINAL_EXES = frozenset({"windowsterminal.exe", "openconsole.exe", "conhost.exe"})


def owner_ok(owner_exe: str, foreground_exe: str) -> bool:
    """An unknown owner (some hosts set the clipboard without an owner window) is accepted, a known foreign one is not."""
    return not owner_exe or owner_exe == foreground_exe or owner_exe in TERMINAL_EXES


def wait_for_copy(snapshot, read_seq, read_owner_exe, foreground_exe, read_text, deadline, current,
                  poll_s=0.05, sleep=time.sleep, now=time.monotonic):
    """Wait until deadline (monotonic) for a terminal-made clipboard change after `snapshot`.

    Returns (status, owner_exe, text); status is "ok", "none" (nothing arrived) or "superseded" (current() went false).
    A change made by another application, or one without usable text, is skipped and the wait continues.
    """
    owner = ""
    while True:
        if not current():
            return "superseded", owner, ""
        seq = read_seq()
        if seq != snapshot:
            snapshot = seq
            owner = read_owner_exe()
            if owner_ok(owner, foreground_exe):
                text = read_text()
                if text and text.strip():
                    return "ok", owner, text
        if now() >= deadline:
            return "none", owner, ""
        sleep(poll_s)
