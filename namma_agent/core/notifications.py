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
  • Windows — a real Action-Center toast via the WinRT
    ``ToastNotificationManager`` (driven from PowerShell), with **Reply** and
    **Open** action buttons that protocol-launch the app's URL (Phase 5).
    Clicking the toast body opens the app too. Falls back to the legacy
    ``NotifyIcon`` balloon inside the same script when WinRT is unavailable
    (older hosts, group policy) — same visible outcome, no buttons.
  • macOS   — ``osascript -e 'display notification …'``.
  • Linux   — ``notify-send`` when present.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess

# PowerShell that pops a toast with Reply/Open buttons, falling back to a balloon.
# Title/body/URLs come in via env vars so we never have to escape user text into
# the script body; inside the script they're XML-escaped before templating.
# The AUMID trick: an unpackaged Python process has no registered app identity,
# but PowerShell's own AUMID is always present, so the toast is attributed to
# "Windows PowerShell" — the accepted route for unpackaged apps. Buttons use
# activationType="protocol" (open a URL), which needs NO COM activator — a true
# inline-reply textbox would, so "Reply" deep-links into the chat view (whose
# composer autofocuses on load; ?reply=1 marks the intent) rather than editing
# in-toast.
_WINDOWS_PS = r"""
$ErrorActionPreference = 'Stop'
try {
  $null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
  $null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
  $t = [Security.SecurityElement]::Escape($env:NAMMA_NOTIFY_TITLE)
  $b = [Security.SecurityElement]::Escape($env:NAMMA_NOTIFY_BODY)
  $u = [Security.SecurityElement]::Escape($env:NAMMA_NOTIFY_URL)
  $r = [Security.SecurityElement]::Escape($env:NAMMA_NOTIFY_REPLY_URL)
  $xml = '<toast activationType="protocol" launch="' + $u + '">' +
         '<visual><binding template="ToastGeneric">' +
         '<text>' + $t + '</text><text>' + $b + '</text>' +
         '</binding></visual>' +
         '<actions>' +
         '<action content="Reply" activationType="protocol" arguments="' + $r + '"/>' +
         '<action content="Open" activationType="protocol" arguments="' + $u + '"/>' +
         '</actions></toast>'
  $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
  $doc.LoadXml($xml)
  $toast = New-Object Windows.UI.Notifications.ToastNotification($doc)
  $aumid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)
} catch {
  # WinRT unavailable (old host / policy) — legacy balloon, no buttons.
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
}
"""


def _app_url() -> str:
    """The local web UI URL toast actions open. Mirrors app.py's default."""
    return os.environ.get("NAMMA_APP_URL") \
        or f"http://127.0.0.1:{os.environ.get('PORT', 8000)}"


# The AUMID we show toasts under (see _WINDOWS_PS) — also the key Windows files
# our per-app notification setting under.
_WIN_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def _windows_toasts_enabled() -> tuple[bool, str]:
    """Will Windows actually *render* a toast right now?

    ``ToastNotification.Show()`` succeeds silently when the user has turned
    notifications off, so spawning the helper tells us nothing. Read the same
    switches the Settings app writes, so we can report the truth instead of a
    false "sent":

      • ``PushNotifications\\ToastEnabled`` = 0 → the master "Notifications"
        switch in Settings → System → Notifications is off; nothing gets through.
      • ``Notifications\\Settings\\<AUMID>\\Enabled`` = 0 → toasts are allowed,
        but muted for the app we publish under.
    """
    try:
        import winreg
    except Exception:  # pragma: no cover - non-Windows
        return True, ""

    def _dword(root: str, name: str):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None  # key/value absent = Windows default = enabled

    if _dword(r"SOFTWARE\Microsoft\Windows\CurrentVersion\PushNotifications",
              "ToastEnabled") == 0:
        return False, ("Windows notifications are turned off. Turn them on in "
                       "Settings → System → Notifications.")
    if _dword(r"SOFTWARE\Microsoft\Windows\CurrentVersion\Notifications\Settings"
              "\\" + _WIN_AUMID, "Enabled") == 0:
        return False, ("Windows has notifications muted for Windows PowerShell, "
                       "which this app posts toasts through. Re-enable it in "
                       "Settings → System → Notifications.")
    return True, ""


def notification_status() -> dict:
    """Can this machine show a native desktop toast? ``{available, reason}``.

    Used by ``/api/notify`` to answer honestly and by the UI to fall back to an
    in-app banner rather than dropping the notification on the floor.
    """
    system = platform.system()
    try:
        if system == "Windows":
            ok, reason = _windows_toasts_enabled()
            return {"available": ok, "reason": reason, "platform": "windows"}
        if system == "Darwin":
            ok = bool(shutil.which("osascript"))
            return {"available": ok, "platform": "macos",
                    "reason": "" if ok else "osascript is unavailable on this Mac."}
        ok = bool(shutil.which("notify-send"))
        return {"available": ok, "platform": "linux",
                "reason": "" if ok else
                          "No notification daemon found — install libnotify "
                          "(notify-send) to get desktop toasts."}
    except Exception:
        return {"available": False, "reason": "", "platform": system.lower()}


def send_native_notification(title: str, body: str = "",
                             url: str | None = None) -> bool:
    """Show a native desktop notification. Returns True if one was dispatched.

    ``url`` is what the toast's Open button (and the toast body) launches;
    defaults to the local web UI. Best-effort and non-blocking: the OS helper
    is spawned detached and we return immediately. Never raises.

    Returns False *without spawning* when the OS is configured to swallow
    toasts — spawning would "succeed" and show nothing, and the caller needs a
    truthful answer so it can fall back to an in-app banner.
    """
    title = (title or "Namma Agent").strip() or "Namma Agent"
    body = (body or "").strip()
    system = platform.system()
    if not notification_status().get("available"):
        return False
    try:
        if system == "Windows":
            open_url = (url or _app_url()).strip()
            reply_url = open_url + ("&" if "?" in open_url else "?") + "reply=1"
            env = {**os.environ,
                   "NAMMA_NOTIFY_TITLE": title, "NAMMA_NOTIFY_BODY": body,
                   "NAMMA_NOTIFY_URL": open_url,
                   "NAMMA_NOTIFY_REPLY_URL": reply_url}
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
