---
name: troubleshooting
description: >
  Diagnose and fix problems on this computer or with an app: slowness, disk
  full, network down, a program crashing, errors in a terminal. Use when the
  user reports something broken or asks "why is X slow / not working". Not for
  general how-to questions with nothing broken.
platforms: [linux, macos, windows]
version: 1.0.0
category: system
metadata:
  hermes:
    tags: [troubleshooting, diagnostics, windows, system]
---

# Troubleshooting

Measure before you change anything.

## Procedure

1. **Reproduce and scope**: what exactly fails, since when, what changed.
2. **Gather facts with read-only checks** — `system_info`, then targeted
   `run_shell` commands (disk: `Get-PSDrive` / `df -h`; processes:
   `Get-Process | Sort CPU -desc | Select -First 10` / `top -bn1`; network:
   `ping_host`, `dns_lookup`, `check_port`). Read error messages fully.
3. **Form a hypothesis** that explains all the facts; test it with one more
   check if possible.
4. **Propose the fix** with what it changes and how to undo it. Destructive or
   system-changing commands need the user's approval — ask first.
5. **Verify** the problem is gone by repeating the check from step 2.

## Gotchas

- Windows uses PowerShell syntax — no `grep`, `rm -rf`, `&&` chains.
- One change at a time, so you know which one fixed it.
