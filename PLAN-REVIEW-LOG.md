# Plan Review Log: Claude CLI Translate (cct)
Started at session start. MAX_ROUNDS=5. Reviewer: GLM-5.3 (read-only). Planner/implementer: Claude.

<system-reminder>
Your final report is delivered through SubagentHandback: when your work is complete, call SubagentHandback({message: <your full report>}). The call ends your run, so make it your last step. Only a SubagentHandback call reaches your caller as your result; plain text you write at the end is not delivered.
</system-reminder>

## Round 1 - GLM (session 86591b79-de21-483b-82a9-a42a189b4a72, 2 turns, 250 s, model glm-5.3)

Read PLAN.md. Good plan — spike-first, hook threading done right, no Ctrl+C. One HIGH found.

## Findings

**[HIGH-1] Clipboard probe destroys non-text clipboard content.** Step 3b snapshots text only, restores text only. User has screenshot (CF_BITMAP) or copied files (CF_HDROP) in clipboard, UIA path fails (VS Code host, a11y tree gated) → probe fires → image/files silently gone. Plan lists it as risk, ships it unmitigated. Fix: skip probe entirely when clipboard contains any non-text format (or full `OleGetClipboard` IDataObject snapshot/restore).

**[MED-1] Esc-close is a spec contradiction.** Popup is `WS_EX_NOACTIVATE` + never focused → it can never receive Esc (no `WM_KEYDOWN` without focus). If "fixed" by polling `GetAsyncKeyState`, the Esc keystroke still lands in Claude Code's input — violates the stated "must not disturb Claude Code's input" goal. Fix: drop Esc-close, keep outside-click + timeout.

**[MED-2] Silent hook death.** LL hook callback is Python code → needs GIL. Any stall past `LowLevelHooksTimeout` (long GC, blocking call holding GIL) → Windows removes hook without any error. Tray alive, feature dead. Fix: liveness watchdog (no events N s while cursor moved → re-install hook) + keep GIL-heavy work off hook thread forever.

**[MED-3] UIA read can block Qt GUI thread.** Plan doesn't pin UIA calls to a worker; comtypes call into busy WT (Claude streaming) can block seconds, freezing icon/tray; also needs per-thread `CoInitialize`. Fix: UIA read in worker thread + `CoInitialize(MTA)` + ~500 ms watchdog, degrade to probe on timeout.

**[MED-4] VS Code terminal probably broken on both paths.** Claim "Ctrl+Insert bound to copy in VS Code terminal" unverified (default terminal copy is Ctrl+C-when-selected / Ctrl+Shift+C; Ctrl+Insert is editor-scope). And Chromium exposes full a11y tree only on AT detection — external UIA client may get textarea-only, empty selection. Fix: verify per-host in spike or drop Code.exe from default allowlist; per-host copy-chord map.

**[MED-5] Icon eats the triple-click.** Double-click word-select → icon at +8,8, 24px, appears 120 ms later — exactly where third click of a triple-click (line select) lands. Click swallowed by icon, WT never sees it, line selection broken. Common gesture. Fix: for click-chains, show icon only after `GetDoubleClickTime` elapses with no further click.

**[MED-6] Probe privacy + races.** Copied terminal text (often secrets) enters Win+V history — on by default on Win11 — and cloud sync if enabled. Also: focus can change between mouse-up and SendInput (keys go to wrong app); other processes can write clipboard between snapshot and restore (clobbered). Fix: set `ExcludeClipboardContentFromMonitorProcessing` format during probe; re-verify foreground is allowlisted terminal immediately before SendInput.

**[MED-7] Proxy hard-bypass risks core feature.** `trust_env=False` assumed fine because "direct works" — but machine runs V2RayN precisely because some destinations fail direct. If `translate.googleapis.com` unreachable direct, every translation errors. Fix: config toggle direct/system-proxy, default direct.

**[MED-8] Log content unspecified.** Debugging instinct logs selections/translations → secrets persist in `%APPDATA%\ClaudeCliTranslate\cct.log`. Fix: spec redaction now — never log raw selected text (length + hash at most), verbose mode opt-in.

**[LOW-1]** "Hide icon when selection is gone" unimplementable — mouse hook gives no selection-change signal. Fix: rely on 4 s timeout + outside click; delete clause.

**[LOW-2]** Fractional DPI (150%): physical↔logical rounding drifts icon/popup placement. Fix: all hit-testing and clamping in physical px, single conversion at Qt boundary.

**[LOW-3]** Rectangular (Alt+drag / block) selections: equal-length lines joined by wrap heuristic → mangled code. Fix: pass block selections through with minimal joining.

**[LOW-4]** Observability gaps: no per-lookup record of which strategy (UIA/probe/cache) served + latency; `pythonw` crashes are silent (stdout is None). Fix: one log line per lookup with strategy+latency; `faulthandler.enable()` to log file.

**[LOW-5]** WT copy clears the selection highlight after Ctrl+Insert probe — user sees selection vanish. Fix: document as known side effect.

Skipped: screenshots (told to ignore), no code exists to cross-check. Risk: WT/conhost UIA claims rest on spike P0 — correct call by plan; my VS Code/Chromium and clipboard-format claims are platform knowledge, not locally verified.

VERDICT: REVISE

### Claude's response (round 1)
Accepted and applied to PLAN.md:
- HIGH-1: probe now skips when clipboard has any non-text format; probe is also opt-in/off by default.
- MED-1: Esc-close dropped; close by outside click / close button.
- MED-2: hook watchdog + minimal hook callback added.
- MED-3: UIA runs in an MTA worker thread with 500 ms watchdog, never on the GUI thread.
- MED-4: VS Code (Code.exe) removed from the default allowlist, becomes opt-in after the spike; per-host copy-chord map added; spike verifies each host.
- MED-5: icon delayed until the double-click window expires for click chains; offset enlarged.
- MED-6 (partly): foreground re-check before SendInput, restore only if the clipboard sequence number is unchanged, probe opt-in. REJECTED the ExcludeClipboardContentFromMonitorProcessing fix as infeasible: that format must be set by the process that writes the clipboard (the terminal), not by cct; side effect documented instead.
- MED-7: proxy_mode auto (direct, one retry via system SOCKS) / direct / system.
- MED-8: logging policy added - never log raw text, one line per lookup, faulthandler.
- LOW-1..LOW-5: selection-gone clause deleted; physical-pixel geometry; code/table skip rule for block selections; per-lookup strategy+latency log and faulthandler; highlight-loss documented.
Rejected: none besides the MED-6 sub-point above.

## Round 2 - GLM (session 86591b79-de21-483b-82a9-a42a189b4a72, 2 turns, 65 s, model glm-5.3)

Re-read Round 1 plan. Prior findings: all 1 HIGH + 8 MED + 5 LOW addressed.

## Prior findings — resolution check

| Prior | Status | Where |
|---|---|---|
| HIGH-1 clipboard data loss | Fixed — EnumClipboardFormats guard skips probe on any non-text format; probe opt-in, default OFF | step 3b |
| MED-1 Esc contradiction | Fixed — no Esc, rationale correct | step 6, decision 7 |
| MED-2 silent unhook | Fixed — cursor-vs-events watchdog + reinstall | step 2 |
| MED-3 UIA blocks GUI | Fixed — MTA worker + 500 ms watchdog (residual below) | step 3a |
| MED-4 VS Code | Fixed — Code.exe opt-in pending spike; per-host chord map | step 8 |
| MED-5 triple-click eaten | Fixed — icon delayed past GetDoubleClickTime for chains | step 2 |
| MED-6 probe privacy/races | Fixed — opt-in OFF; foreground re-verify; sequence-number guard. Rejection of ExcludeClipboardContentFromMonitorProcessing is technically correct: terminal's write is a fresh content set, can't pre-arm (replaced) or post-arm (history snapshots at write time) | step 3b |
| MED-7 proxy bypass | Fixed — proxy_mode auto/direct/system, one SOCKS retry via PySocks | step 7 |
| MED-8 log secrets | Fixed — no raw text, strategy+latency lines, faulthandler + excepthook | step 8 |
| LOW-1..5 | All fixed (selection-gone clause dropped, physical-px geometry, block-selection skip rule, observability, highlight-loss documented) | various |

Deliberate rejection (Exclude format) checked — reasoning sound.

## New findings (non-blocking)

**[MED-A] Watchdog reinstall from wrong thread.** Qt timer reinstalls hook → WH_MOUSE_LL callbacks then dispatch on the installing thread = Qt GUI thread → mouse events queue behind GUI work → GUI stalls, the exact disaster the design avoids. Fix: timer only flags; dedicated hook thread executes the uninstall/reinstall itself (it owns the message pump).

**[MED-B] UIA watchdog leaves zombie threads.** Python threads can't be cancelled; a comtypes call hung >500 ms is discarded but keeps running, holding the MTA apartment. Repeated hangs (busy WT streaming) accumulate threads. Fix: one replaceable read worker; if previous still alive at next request, mark UIA unhealthy and skip strategy until it exits.

**[LOW-1]** Double-click word-select now waits ~GetDoubleClickTime (default 500 ms) before icon — noticeably slower than reference extension UX. Acceptable tradeoff; note in docs.

**[LOW-2]** Restore "only if sequence number unchanged" is check-then-act TOCTOU — tiny window where another app's write gets clobbered by restore. Accepted cost of opt-in probe; fine.

**[LOW-3]** `uiautomation` package is not a comtypes-independent fallback — it wraps comtypes too. True last resort = raw ctypes COM. comtypes is pure Python, so 3.14 risk minimal anyway; verify in spike.

**[LOW-4]** Watchdog false-positives during secure desktop (UAC prompt: cursor moves, no events) → harmless spurious reinstall + log noise. Ignore or gate on foreground-unlock.

Skipped: screenshots, repo code — none relevant; no runtime verification possible read-only.

VERDICT: APPROVED

### Non-blocking follow-ups (from round 2)
MED-A (reinstall hook on the hook thread, not the GUI thread) and MED-B (single replaceable UIA worker, mark UIA unhealthy while a hung call lives) accepted and copied into PLAN.md under "Round 2 follow-ups". LOW items (double-click icon delay note, comtypes-vs-uiautomation fallback and Python 3.14 check, UAC false positive, clipboard restore TOCTOU) accepted as documented, no plan change needed.

### Result
CONVERGED: VERDICT APPROVED in round 2 of MAX_ROUNDS=5. One deliberate rejection (ExcludeClipboardContentFromMonitorProcessing), confirmed sound by GLM.

## Round 3 - GLM confirmation (session 86591b79-de21-483b-82a9-a42a189b4a72, 2 turns, 19 s, model glm-5.3)

Re-read. Follow-ups check:

| Item | Captured faithfully? |
|---|---|
| MED-A reinstall thread | Yes — timer flags only, hook thread (owns pump) executes uninstall/reinstall. Correct mechanism. |
| MED-B zombie UIA worker | Yes — one replaceable worker, mark unhealthy, skip until exit, log. Matches fix. |
| LOW double-click latency note | Yes |
| LOW uiautomation-wraps-comtypes + verify 3.14 in spike | Yes |
| LOW secure-desktop false positive | Yes |
| LOW restore TOCTOU accepted | Yes |

No contradictions of substance. One wording nit:

**[LOW]** Step 2 body still says the Qt timer does "uninstall + reinstall" — the Round 2 follow-up reverses that. Implementer coding P1 from the body alone would put the reinstall on the GUI thread, the exact bug MED-A forbids. Fix: one-line edit in step 2 ("watchdog detects; reinstall runs on the hook thread — see Round 2 follow-ups"). Same for the stale "Round 1" header line. Cosmetic, non-blocking.

Nothing new beyond that. No HIGH, no MED.

Skipped: nothing — single-file diff re-check, no runtime verification possible.

VERDICT: APPROVED

### Claude's response (round 3)
GLM APPROVED again; only a cosmetic LOW (step 2 body vs MED-A, stale header) - both wording fixes applied to PLAN.md. FINAL: APPROVED in round 3 of MAX_ROUNDS=5.

## Phase 0 evidence and redesign (Claude, after round 3)
Phase 0 spike (spike/p0_uia_spike.py, spike/p0b_uia_retry.py) measured on Windows Terminal 1.24 + Claude Code (windowed): UIA reads Shift+drag and ordinary shell selections reliably (50 ms, no retry benefit, rows padded with trailing spaces); a plain drag in Claude Code is handled by Claude Code itself (UIA empty, auto-copy to clipboard); the Ctrl+Insert probe is unnecessary. User added a requirement: act ONLY on Shift+drag. PLAN.md was rewritten (Round 4): trigger gated on Shift at button-down, UIA-only read, probe and all clipboard access removed, click-chain handling removed, Round-2 follow-ups folded into the body. Sent back to GLM for round 4.

## Round 4 - GLM (session 86591b79-de21-483b-82a9-a42a189b4a72, 2 turns, 141 s, model glm-5.3)

Read Round 4 plan fresh. Redesign is sound: dropping the clipboard path kills the whole risk class (no data loss, no keystroke injection, no privacy races); UIA-only matches measured evidence; watchdog and worker rules from Round 2 folded correctly into the body (step 2, step 3).

## Answers to the four questions

**UIA-only + Shift gating holds?** Yes for the measured configuration. Phase 0 shows WT TextPattern returns Shift+drag selections (3/3 CC tab, 9/9 plain shell) and explains *why* (Shift bypasses Claude Code's own mouse handling, result 3). Evidence is one machine / one WT version / normal window only — the plan says so itself and defers fullscreen, conhost, VS Code to P4. Honest.

**Shift-at-button-down sampling in the LL callback sound?** API choice correct — mouse hook structs carry no modifier state, `GetAsyncKeyState` is the right call (not `GetKeyState`, which is per-thread input-state). One skew: async state is sampled when the Python callback finally runs; GIL contention can delay it past the physical button-down. Bounded — Shift is normally held before button-down and through the drag, so delay of a few ms rarely flips the sample. Mismatch vs WT's own sampling only in freak timing. LOW.

**Mouse-up → UIA read race?** Sound. Text stable from 50 ms (measured), read at 60 ms + one 250 ms retry covers it; selection cleared by user's next click → empty → no icon, which is correct. No debounce needed anymore since empty-read is the gate.

**Clipboard-drop gaps?** Deliberate and documented: plain-drag-in-Claude-Code path is dead by design (reading the auto-copy was rejected for privacy — right call), unverified hosts simply no-op. No gap that matters.

## New findings (non-blocking)

**[MED-1] spike/ logs vs GitHub origin — no enforcement.** Repo now has a public origin; spike logs "contain short text heads" of terminal output and the plan only *says* "must not be committed". One `git add .` publishes terminal content. Fix: P1 creates `.gitignore` with `spike/` (or `spike/*.log`) before any push; also consider purging if already staged.

**[MED-2] Block-selection claim has no evidence and lost its test.** Normalisation (step 4) still claims block-selection handling, Phase 0 never measured Alt+Shift+drag (block selections come back as per-line ranges — different shape than tested), and Round 4's manual matrix dropped the "Alt+drag block selection" row that earlier rounds had. Fix: restore that row to the P4 matrix or delete the block-selection claim from step 4.

**[LOW-1]** Goal line 5 says "never reads or writes the clipboard" — contradicted by the copy-translation button (step 6, the app's one clipboard write). Fix: reword to "no clipboard access except the explicit copy button".

**[LOW-2]** Focus race at read time: foreground is checked at mouse-up, but `GetFocusedElement` runs ~60 ms later — an alt-tab in that window could read a selection from a non-allowlisted app (icon then requires an explicit click, so exposure is one user action). Fix: re-verify foreground allowlist inside the worker just before the UIA call.

**[LOW-3]** `sys.coinit_flags = 0` is process-global MTA; Qt's GUI thread initializes OLE/STA (`OleInitialize`) — the Phase 0 recipe was verified in a bare script, not inside a PySide6 app. Fix: P2 keeps every comtypes touch on the worker thread only and verifies import order inside the real app.

**[LOW-4]** Shift sampling skew under GIL delay (above). Fix: sample at button-down AND button-up, accept if either is down; log both in verbose mode.

**[LOW-5]** Selection read during active Claude Code streaming (buffer growing under the selection) untested — Phase 0 measured idle output only. Fix: add one streaming case to the P4 matrix.

**[LOW-6]** conhost.exe/OpenConsole.exe sit in the default allowlist unverified — worst case silent no-op. Fix (already implied by P4): move them in only after verification, like Code.exe.

Skipped: spike/ contents per instruction; screenshots; no runtime checks — read-only review of PLAN.md only.

VERDICT: APPROVED

### Claude's response (round 4)
GLM APPROVED the redesign (UIA-only, Shift gating, no clipboard). All follow-ups accepted and applied to PLAN.md: MED-1 .gitignore for spike/ added to P1; MED-2 block-selection claim marked unmeasured and Alt+Shift+drag row restored to the P4 matrix; LOW-1 goal wording fixed (copy button is the only clipboard write); LOW-2 foreground re-verified inside the UIA worker; LOW-3 comtypes/MTA import order to be re-verified inside the PySide6 app in P2; LOW-4 Shift sampled at button-down and button-up; LOW-5 streaming case added to the P4 matrix; LOW-6 conhost/OpenConsole/Code.exe removed from the default allowlist until verified. Wording and test-matrix changes only; not re-sent to GLM. FINAL: APPROVED in round 4 (rounds used: 4 of MAX_ROUNDS=5 for the redesign; 3 for the original design).
