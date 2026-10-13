_Status: all items verified by the user on the Windows machine (VS Code skipped by decision)._

# Phase 4 manual test checklist

Do this on the Windows machine. `git pull` first, then `python -m pytest -q tests` (expect 88 passed).
Write the result next to each line (OK / FAIL / note). Send me the FAIL lines and the tail of
`%APPDATA%\ClaudeCliTranslate\cct.log` (it never contains selected text).

## A. Verify Phase 3 and the 429 fix (before anything else)
- [x] App starts with `pythonw run.pyw`; first-run balloon appears once, not on the second start
- [x] Tray menu shows: Enabled, Target language, Scope, Font size, Start with Windows, Open log, Quit
- [x] Target language: pick English, Shift+drag Russian text, popup header says `ru → en`
- [x] Enabled off: Shift+drag shows no icon; on again: icon appears
- [x] Scope = All applications: Shift+drag in Notepad shows an icon (UIA may return nothing there; the point is the trigger passes the scope check - see log line "trigger exe=notepad.exe"); back to Terminals only: Notepad is ignored
- [x] Start with Windows ticked: value `ClaudeCliTranslate` exists under HKCU\Software\Microsoft\Windows\CurrentVersion\Run and points to pythonw.exe + run.pyw; unticked: value is gone
- [x] Start a second copy (`pythonw run.pyw`): it exits, no second tray icon
- [x] Open log opens cct.log
- [x] Restart: language, scope, font size, enabled state are remembered
- [x] 429 / Retry: turn V2RayN off and set `"proxy_mode": "direct"` in settings.json, translate, then block translate.googleapis.com
      (hosts file entry `127.0.0.1 translate.googleapis.com`) - popup shows an error with a Retry button; remove the entry, click Retry, translation appears. Log shows `try=` and `via=` lines.

## B. Terminal hosts (run `python tools/probe_host.py`, then use the app)
For each: does the probe print `TextPattern ok` with chars > 0, and does the app show the icon and a translation?
- [x] conhost / classic console: UIA reads the selection (probe: foreground exe cmd.exe, class ConsoleWindowClass, 2035 chars). Now matched by window class.
- [x] conhost end to end with the app (verified by the user): Shift+drag in a classic console window (`conhost.exe cmd.exe` via Win+R) shows the icon and the translation
- [x] OpenConsole.exe (if the exe name differs)
- [-] VS Code integrated terminal: skipped, not needed by the user
- [x] Windows Terminal, Claude Code in fullscreen mode
- [x] Windows Terminal, Alt+Shift+drag (block selection): text shape and normalisation
- [x] Selecting while Claude Code is streaming output (selection survives / icon appears)
- [x] Elevated (Administrator) terminal: expected NO reaction (UIPI); confirm and that nothing crashes

## C. Display
- [x] 100% DPI: icon and popup next to the pointer, popup inside the screen
- [x] 150% DPI: same, no offset or blur
- [x] Second monitor with a different scale: icon/popup on the right monitor
- [x] Selection near the right and bottom screen edges: popup clamped

## D. Misc
- [x] Clipboard holding an image stays untouched after a translation (only Copy button writes)
- [x] V2RayN on and off both translate
- [x] Plain drag (no Shift) does nothing
