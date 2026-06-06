"""Vision tools — screen capture and OCR. Cross-platform, CLI-backed.

The v2 agent's message channel is text-only, so true visual *description*
(describe a meme, review a UI) is deferred until the agent gains multimodal
image input. What works today in the text channel ships here:

  take_screenshot      — capture the screen to a PNG, return the path
  read_text_from_image — OCR an image to text (tesseract)

Both degrade gracefully with a clear error when the backing tool is absent.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import time

from friday.core.safety import check_path
from friday.core.tools import ToolRegistry, ToolResult


def _screenshot_argv(out_path: str) -> list[str] | None:
    """Pick a capture command for the current platform, or None if none found."""
    system = platform.system()
    if system == "Darwin":
        return ["screencapture", "-x", out_path]
    if system == "Windows":
        ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
              "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
              "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
              "$g=[System.Drawing.Graphics]::FromImage($bmp); "
              "$g.CopyFromScreen(0,0,0,0,$bmp.Size); "
              f"$bmp.Save('{out_path}')")
        return ["powershell", "-NoProfile", "-Command", ps]
    # Linux: try Wayland (grim) then X11 (scrot / gnome-screenshot / spectacle)
    for tool, argv in (("grim", ["grim", out_path]),
                       ("scrot", ["scrot", "-o", out_path]),
                       ("gnome-screenshot", ["gnome-screenshot", "-f", out_path]),
                       ("spectacle", ["spectacle", "-b", "-n", "-o", out_path]),
                       ("import", ["import", "-window", "root", out_path])):
        if shutil.which(tool):
            return argv
    return None


def _take_screenshot(args: dict) -> ToolResult:
    path = (args.get("path") or "").strip()
    if path:
        ok, reason = check_path(path)
        if not ok:
            return ToolResult(ok=False, content="", error=reason)
        out = os.path.expanduser(path)
    else:
        out = os.path.join(tempfile.gettempdir(), f"friday_screenshot_{int(time.time())}.png")

    argv = _screenshot_argv(out)
    if argv is None:
        return ToolResult(ok=False, content="",
                          error="no screenshot tool found (install grim/scrot/gnome-screenshot)")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20)
    except FileNotFoundError:
        return ToolResult(ok=False, content="", error=f"{argv[0]!r} not found")
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, content="", error="screenshot timed out")
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        return ToolResult(ok=False, content="", error=f"capture failed: {proc.stderr.strip()[:200]}")
    return ToolResult(ok=True, content=f"Screenshot saved to {out}", data={"path": out})


def _read_text(args: dict) -> ToolResult:
    path = (args.get("path") or "").strip()
    ok, reason = check_path(path)
    if not ok:
        return ToolResult(ok=False, content="", error=reason)
    img = os.path.expanduser(path)
    if not os.path.isfile(img):
        return ToolResult(ok=False, content="", error=f"not a file: {path}")
    if not shutil.which("tesseract"):
        return ToolResult(ok=False, content="", error="OCR needs tesseract (install tesseract-ocr)")
    try:
        proc = subprocess.run(["tesseract", img, "stdout"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, content="", error="OCR timed out")
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 and not text:
        return ToolResult(ok=False, content="", error=f"tesseract failed: {proc.stderr.strip()[:200]}")
    return ToolResult(ok=True, content=text or "(no text detected in image)")


def register(registry: ToolRegistry) -> None:
    registry.register("take_screenshot", "Capture the screen to a PNG file and return its path.", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "optional output path (default: temp dir)"}},
    }, _take_screenshot)

    registry.register("read_text_from_image", "Extract text from an image file via OCR (tesseract).", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "path to the image file"}},
        "required": ["path"],
    }, _read_text)
