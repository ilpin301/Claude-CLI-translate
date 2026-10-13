# Phase 4 manual test checklist

Do this on the Windows machine. `git pull` first, then `python -m pytest -q tests` (expect 88 passed).
Write the result next to each line (OK / FAIL / note). Send me the FAIL lines and the tail of
`%APPDATA%\ClaudeCliTranslate\cct.log` (it never contains selected text).

## A. Verify Phase 3 and the 429 fix (before anything else)
- [ ] App starts with `pythonw run.pyw`; first-run balloon appears once, not on the second start
- [ ] Tray menu shows: Enabled, Target language, Scope, Font size, Start with Windows, Open log, Quit
- [ ] Target language: pick English, Shift+drag Russian text, popup header says `ru → en`
- [ ] Enabled off: Shift+drag shows no icon; on again: icon appears
- [ ] Scope = All applications: Shift+drag in Notepad shows an icon (UIA may return nothing there; the point is the trigger passes the scope check - see log line "trigger exe=notepad.exe"); back to Terminals only: Notepad is ignored
- [ ] Start with Windows ticked: value `ClaudeCliTranslate` exists under HKCU\Software\Microsoft\Windows\CurrentVersion\Run and points to pythonw.exe + run.pyw; unticked: value is gone
- [ ] Start a second copy (`pythonw run.pyw`): it exits, no second tray icon
- [ ] Open log opens cct.log
- [ ] Restart: language, scope, font size, enabled state are remembered
- [ ] 429 / Retry: turn V2RayN off and set `"proxy_mode": "direct"` in settings.json, translate, then block translate.googleapis.com
      (hosts file entry `127.0.0.1 translate.googleapis.com`) - popup shows an error with a Retry button; remove the entry, click Retry, translation appears. Log shows `try=` and `via=` lines.

## B. Terminal hosts (run `python tools/probe_host.py`, then use the app)
For each: does the probe print `TextPattern ok` with chars > 0, and does the app show the icon and a translation?
- [x] conhost / classic console: UIA reads the selection (probe: foreground exe cmd.exe, class ConsoleWindowClass, 2035 chars). Now matched by window class.
- [ ] conhost end to end with the app: Shift+drag in a classic console window (`conhost.exe cmd.exe` via Win+R) shows the icon and the translation
- [ ] OpenConsole.exe (if the exe name differs)
- [ ] VS Code integrated terminal (Code.exe)
- [ ] Windows Terminal, Claude Code in fullscreen mode
- [ ] Windows Terminal, Alt+Shift+drag (block selection): text shape and normalisation
- [ ] Selecting while Claude Code is streaming output (selection survives / icon appears)
- [ ] Elevated (Administrator) terminal: expected NO reaction (UIPI); confirm and that nothing crashes

## C. Display
- [ ] 100% DPI: icon and popup next to the pointer, popup inside the screen
- [ ] 150% DPI: same, no offset or blur
- [ ] Second monitor with a different scale: icon/popup on the right monitor
- [ ] Selection near the right and bottom screen edges: popup clamped

## D. Misc
- [ ] Clipboard holding an image stays untouched after a translation (only Copy button writes)
- [ ] V2RayN on and off both translate
- [ ] Plain drag (no Shift) does nothing
