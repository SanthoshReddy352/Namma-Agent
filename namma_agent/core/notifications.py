"""Native OS desktop notifications.

Local-first reliability fix: the browser Notification API does **not** surface as a
real toast inside the pywebview / WebView2 desktop window, so notifications quietly
did nothing in the desktop app. Because Namma's server runs on the same machine as
the user, the dependable place to show a desktop toast is the *backend* — it can
call the platform's own notification mechanism.

The frontend decides *whether* to notify (honouring the user's master + per-event
toggles) and POSTs the title/body to ``/api/notify``; this module just displays it.
Everything is best-effort, non-blocking, and never raises — a machine without a
notifier simply gets no toast.

Platform mechanisms (all stdlib / OS built-ins, no new Python deps):
  • Windows — a tray balloon via ``System.Windows.Forms.NotifyIcon`` (Win10/11 route
    these into the Action Center as toasts); spawned detached so it never blocks.
  • macOS   — ``osascript -e 'display notification …'``.
  • Linux   — ``notify-send`` when present.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess

# PowerShell that pops a balloon/toast. Title/body come in via env vars so we never
# have to escape user text into the script body.
_WINDOWS_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.BalloonTipTitle = $env:NAMMA_NOTIFY_TITLE
$n.BalloonTipText = $env:NAMMA_NOTIFY_BODY
$n.Visible = $true
$n.ShowBalloonTip(6000)
Start-Sleep -Milliseconds 7000
$n.Dispose()
"""


def send_native_notification(title: str, body: str = "") -> bool:
    """Show a native desktop notification. Returns True if one was dispatched.

    Best-effort and non-blocking: the OS helper is spawned detached and we return
    immediately. Never raises.
    """
    title = (title or "Namma Agent").strip() or "Namma Agent"
    body = (body or "").strip()
    system = platform.system()
    try:
        if system == "Windows":
            env = {**os.environ, "NAMMA_NOTIFY_TITLE": title, "NAMMA_NOTIFY_BODY": body}
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                 "-Command", _WINDOWS_PS],
                env=env, creationflags=DETACHED_PROCESS,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
            return True
        if system == "Darwin":
            t = title.replace("\\", "\\\\").replace('"', '\\"')
            b = body.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(
                ["osascript", "-e", f'display notification "{b}" with title "{t}"'],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        # Linux / *nix
        if shutil.which("notify-send"):
            subprocess.Popen(
                ["notify-send", "-a", "Namma Agent", title, body],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
    except Exception:
        return False
    return False
