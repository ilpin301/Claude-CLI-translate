---
name: session-handoff
description: Write a handoff summary so a new session can continue this work. Use when the user types /session-handoff or asks to hand off the session.
---

Write a handoff summary of this session for a fresh session that has no memory of it. Check the real state first with `git status -sb`, `git log --oneline -5` and `git stash list`; do not rely on memory.

Use these sections:
1. **User request**: what the user wants, in one or two lines
2. **What was done**: concrete steps and decisions, including what was verified and by whom
3. **Current state**: branch, uncommitted changes, stashes, open PRs, and anything blocked
4. **Unfinished work**: next steps in order, with exact commands where useful
5. **Gotchas**: facts the next session must not re-derive (measurements, env limits, rejected options)

Keep it under about 40 lines. Never include secrets or tokens. Save it to `HANDOFF.md` in the repo root and print it, but do not commit it unless asked.
