"""Controlled browser via Playwright — a real, visible browser FRIDAY drives,
using the user's *preferred* browser and a *persistent* profile so accounts stay
signed in.

Playwright's *sync* API objects are single-threaded, so every browser call runs on
ONE dedicated worker thread fed by a command queue; tool handlers (which run on the
server's worker threads) submit a callable and block on the result. The window is
**headed/visible** — the user watches playback while FRIDAY issues controls.

Profile / browser selection:
  * ``browser.preferred: auto`` detects the OS default browser (chrome / chromium /
    brave / edge / vivaldi / opera / firefox) and drives that binary.
  * A **persistent** ``launch_persistent_context`` keeps cookies/logins between runs.
    By default it uses a dedicated dir (``~/.friday/browser-profile``) — sign in once
    and it's cached forever. Set ``use_system_profile: true`` to reuse the real
    browser profile (close that browser first; falls back safely if it's locked).

Falls back gracefully: :meth:`available` is False when Playwright isn't installed,
and the browser tools then degrade to the stdlib ``webbrowser`` path.
"""
from __future__ import annotations

import platform
import queue
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Optional

from friday.core.logger import logger

_NAV_TIMEOUT = 30_000  # ms

# A clean, modern Chrome UA. YouTube Music rejects the default headless UA
# ("Your browser is deprecated"); this also strips the "HeadlessChrome" token.
_CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Chromium-family browser id → Playwright channel (used only if no real binary).
_CHANNELS = {"chrome": "chrome", "edge": "msedge"}
# Chromium-family browser id → candidate executable names on PATH.
_EXECUTABLES = {
    "chrome": ["google-chrome-stable", "google-chrome", "chrome"],
    "chromium": ["chromium", "chromium-browser"],
    "brave": ["brave-browser-stable", "brave-browser", "brave"],
    "edge": ["microsoft-edge-stable", "microsoft-edge"],
    "vivaldi": ["vivaldi-stable", "vivaldi"],
    "opera": ["opera"],
}
# Subdirs/files NOT worth copying from a real profile (caches + lock files).
_PROFILE_SKIP = ("Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
                 "DawnWebGPUCache", "ShaderCache", "GrShaderCache", "Service Worker",
                 "Application Cache", "Crashpad", "component_crx_cache", "extensions_crx_cache")
# Per-OS user-data-dir for reusing the real signed-in profile.
_PROFILE_DIRS = {
    "Linux": {
        "chrome": "~/.config/google-chrome",
        "chromium": "~/.config/chromium",
        "brave": "~/.config/BraveSoftware/Brave-Browser",
        "edge": "~/.config/microsoft-edge",
        "vivaldi": "~/.config/vivaldi",
        "opera": "~/.config/opera",
        "firefox": "~/.mozilla/firefox",
    },
    "Darwin": {
        "chrome": "~/Library/Application Support/Google/Chrome",
        "chromium": "~/Library/Application Support/Chromium",
        "brave": "~/Library/Application Support/BraveSoftware/Brave-Browser",
        "edge": "~/Library/Application Support/Microsoft Edge",
    },
    "Windows": {
        "chrome": "~/AppData/Local/Google/Chrome/User Data",
        "edge": "~/AppData/Local/Microsoft/Edge/User Data",
        "brave": "~/AppData/Local/BraveSoftware/Brave-Browser/User Data",
    },
}

# JS run inside the page to act on the current <video> element (YouTube + YT Music).
_MEDIA_JS = r"""
([action, seconds]) => {
  const v = document.querySelector('video');
  const click = (sels) => { for (const s of sels) { const el = document.querySelector(s); if (el) { el.click(); return true; } } return false; };
  const NEXT = ['.ytp-next-button', 'ytmusic-player-bar .next-button', 'tp-yt-paper-icon-button.next-button', '.next-button'];
  const PREV = ['.ytp-prev-button', 'ytmusic-player-bar .previous-button', 'tp-yt-paper-icon-button.previous-button', '.previous-button'];
  if (action === 'next') { if (!click(NEXT)) history.forward(); }
  else if (action === 'previous') { if (!click(PREV)) history.back(); }
  else if (v) {
    switch (action) {
      case 'play': v.play(); break;
      case 'pause': v.pause(); break;
      case 'toggle': v.paused ? v.play() : v.pause(); break;
      case 'forward': v.currentTime = Math.min((v.duration||1e9), v.currentTime + seconds); break;
      case 'back': v.currentTime = Math.max(0, v.currentTime - seconds); break;
      case 'restart': v.currentTime = 0; v.play(); break;
      case 'stop': v.pause(); v.currentTime = 0; break;
      case 'volume': v.volume = Math.max(0, Math.min(1, seconds)); break;
    }
  }
  return v ? {paused: v.paused, position: v.currentTime, duration: v.duration} : {paused: null};
}
"""

_STATUS_JS = r"""
() => {
  const v = document.querySelector('video');
  return {
    title: document.title,
    url: location.href,
    playing: v ? !v.paused : false,
    position: v ? v.currentTime : null,
    duration: v ? v.duration : null,
  };
}
"""


def detect_default_browser() -> str:
    """Best-effort id of the OS default browser ('' if unknown)."""
    system = platform.system()
    out = ""
    try:
        if system == "Linux" and shutil.which("xdg-settings"):
            out = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip().lower()
    except Exception:  # noqa: BLE001
        out = ""
    for key in ("brave", "vivaldi", "opera", "firefox", "chromium", "edge"):
        if key in out:
            return key
    if "chrome" in out:  # google-chrome — checked after 'chromium'
        return "chrome"
    return ""


class BrowserController:
    def __init__(
        self,
        headless: bool = False,
        preferred: str = "auto",
        use_system_profile: bool = False,
        profile_dir: str = "~/.friday/browser-profile",
        fullscreen: bool = True,
    ):
        self.headless = headless
        self.preferred = (preferred or "auto").lower()
        self.use_system_profile = use_system_profile
        self.profile_dir = profile_dir
        self.fullscreen = fullscreen
        self._cmd_q: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._start_error: Optional[str] = None
        self.active_browser = ""  # resolved browser id, set once launched

    # -- availability ------------------------------------------------------

    @staticmethod
    def available() -> bool:
        try:
            import playwright.sync_api  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    # -- launch resolution -------------------------------------------------

    def _resolve_browser(self) -> str:
        if self.preferred and self.preferred != "auto":
            return self.preferred
        return detect_default_browser() or "chrome"

    def _resolve_executable(self, browser_id: str) -> Optional[str]:
        """Path to the real installed browser binary, if present."""
        for name in _EXECUTABLES.get(browser_id, []):
            exe = shutil.which(name)
            if exe:
                return exe
        return None

    def _system_profile_dir(self, browser_id: str) -> Optional[Path]:
        path = _PROFILE_DIRS.get(platform.system(), {}).get(browser_id)
        if not path:
            return None
        p = Path(path).expanduser()
        return p if p.exists() else None

    def _prepare_profile(self, browser_id: str) -> str:
        """Return a user-data-dir to launch with.

        With ``use_system_profile`` we COPY the real profile's logins (Local State +
        the Default profile, minus caches) into a dedicated dir once. That keeps the
        user signed in while avoiding (a) the lock conflict with a running browser
        and (b) Chrome's block on driving the *default* user-data-dir directly.
        """
        dedicated = Path(self.profile_dir).expanduser().with_name(
            Path(self.profile_dir).name + f"-{browser_id}")
        dedicated.mkdir(parents=True, exist_ok=True)
        if self.use_system_profile:
            src = self._system_profile_dir(browser_id)
            if src and not (dedicated / "Default").exists():
                self._copy_profile(src, dedicated)
                self._profile_label = f"copy-of-{browser_id}"
            else:
                self._profile_label = f"copy-of-{browser_id}" if src else "dedicated"
        else:
            self._profile_label = "dedicated"
        return str(dedicated)

    @staticmethod
    def _copy_profile(src: Path, dst: Path) -> None:
        try:
            ls = src / "Local State"
            if ls.exists():
                shutil.copy2(ls, dst / "Local State")
            src_def = src / "Default"
            if src_def.exists():
                shutil.copytree(
                    src_def, dst / "Default",
                    ignore=shutil.ignore_patterns(*_PROFILE_SKIP, "*.lock", "Singleton*", "lockfile"),
                    dirs_exist_ok=True, symlinks=True, ignore_dangling_symlinks=True,
                )
            logger.info("[browser] copied real profile logins from %s", src)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser] profile copy partial/failed: %s", exc)

    # -- worker thread -----------------------------------------------------

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._ready.clear()
            self._start_error = None
            self._thread = threading.Thread(target=self._run, name="friday-browser", daemon=True)
            self._thread.start()

    @staticmethod
    def _is_dead(page) -> bool:
        try:
            return page is None or page.is_closed()
        except Exception:  # noqa: BLE001
            return True

    @staticmethod
    def _closed_error(exc: Exception) -> bool:
        """True for Playwright errors that mean the page/context/browser is gone."""
        msg = str(exc).lower()
        return ("has been closed" in msg or "target page" in msg
                or "target closed" in msg or "browser closed" in msg)

    def _boot(self, pw):
        """Launch the configured context and return a live ``(context, page)``.

        Re-runs the *configured* launch (so the persistent profile — and any logins
        cached in it, e.g. a YouTube Premium sign-in — are reused), then probes
        liveness: driving the user's *real* browser while it is already running hands
        the launch off to the existing instance, which then exits and kills our
        context — but the page only dies on the FIRST navigation, so the launch looks
        successful. If the probe shows it dead, recover on bundled Chromium."""
        context = self._launch_context(pw)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("about:blank", timeout=5_000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser] %s context died on probe (%s); recovering on bundled Chromium",
                           self.active_browser, exc)
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass
            context = self._launch_bundled(pw)
            page = context.pages[0] if context.pages else context.new_page()
        return context, page

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright

            pw = sync_playwright().start()
            context, page = self._boot(pw)
        except Exception as exc:  # noqa: BLE001
            self._start_error = str(exc)
            self._ready.set()
            logger.warning("[browser] launch failed: %s", exc)
            return
        self._ready.set()
        logger.info("[browser] %s ready (profile=%s, headless=%s)",
                    self.active_browser, self._profile_label, self.headless)
        try:
            while True:
                item = self._cmd_q.get()
                if item is None:
                    break
                fn, fut = item
                try:
                    # The user may have closed the window between turns. If the page is
                    # gone — or the command fails because it's gone — relaunch (reusing
                    # the same signed-in profile) and retry once, so a second "play"
                    # actually plays instead of falling back to a plain search link.
                    if self._is_dead(page):
                        raise RuntimeError("browser window was closed")
                    fut["result"] = fn(page)
                except Exception as exc:  # noqa: BLE001
                    if self._is_dead(page) or self._closed_error(exc):
                        logger.info("[browser] page/context gone (%s); relaunching and retrying", exc)
                        try:
                            try:
                                context.close()
                            except Exception:  # noqa: BLE001
                                pass
                            context, page = self._boot(pw)
                            fut["result"] = fn(page)
                        except Exception as exc2:  # noqa: BLE001
                            fut["error"] = str(exc2)
                    else:
                        fut["error"] = str(exc)
                finally:
                    fut["done"].set()
        finally:
            for closer in (context.close, pw.stop):
                try:
                    closer()
                except Exception:  # noqa: BLE001
                    pass

    def _chromium_args(self) -> list[str]:
        # Anti-automation flags so YouTube/Google don't throw "something went wrong"
        # at a browser they think is a bot, plus autoplay + optional fullscreen.
        args = [
            "--autoplay-policy=no-user-gesture-required",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run", "--no-default-browser-check",
        ]
        if self.fullscreen and not self.headless:
            args.append("--start-fullscreen")
        return args

    def _launch_context(self, pw):
        """Launch the user's real browser (preferred) on a copy of their profile, so
        accounts stay signed in and playback isn't flagged as automation. Falls back
        to bundled Chromium on a dedicated profile if the real binary can't launch."""
        browser_id = self._resolve_browser()
        engine = "firefox" if browser_id == "firefox" else "chromium"
        user_data_dir = self._prepare_profile(browser_id)

        if engine == "firefox":
            ctx = pw.firefox.launch_persistent_context(user_data_dir, headless=self.headless, no_viewport=True)
            self.active_browser = "firefox"
            return ctx

        exe = self._resolve_executable(browser_id)
        opts = {}
        if exe:
            opts["executable_path"] = exe
        elif browser_id in _CHANNELS:
            opts["channel"] = _CHANNELS[browser_id]
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir, headless=self.headless, no_viewport=True,
                args=self._chromium_args(), ignore_default_args=["--enable-automation"], **opts,
            )
            self.active_browser = f"{browser_id}{' (real)' if exe else ''}"
            self._harden(ctx)
            return ctx
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser] %s launch failed (%s); falling back to bundled Chromium",
                           browser_id, exc)

        return self._launch_bundled(pw)

    def _launch_bundled(self, pw):
        """Bundled Chromium on a dedicated profile (UA spoof so YT Music works).

        Used both as the launch fallback and as the runtime recovery path when the
        configured browser's context dies — it has its own user-data-dir, so it never
        conflicts with the user's already-running browser."""
        fallback = str(Path(self.profile_dir).expanduser().with_name(
            Path(self.profile_dir).name + "-bundled"))
        Path(fallback).mkdir(parents=True, exist_ok=True)
        self._profile_label = "dedicated(bundled)"
        self.active_browser = "chromium(bundled)"
        ctx = pw.chromium.launch_persistent_context(
            fallback, headless=self.headless, no_viewport=True, user_agent=_CHROME_UA,
            args=self._chromium_args(), ignore_default_args=["--enable-automation"],
        )
        self._harden(ctx)
        return ctx

    @staticmethod
    def _harden(ctx) -> None:
        """Mask the obvious automation tells so video sites don't block playback."""
        try:
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
        except Exception:  # noqa: BLE001
            pass

    _profile_label = "dedicated"

    def _call(self, fn: Callable[[Any], Any], timeout: float = 60.0) -> Any:
        self._ensure_thread()
        if not self._ready.wait(timeout=60):
            raise RuntimeError("browser did not start in time")
        if self._start_error:
            raise RuntimeError(f"browser unavailable: {self._start_error}")
        fut: dict = {"done": threading.Event(), "result": None, "error": None}
        self._cmd_q.put((fn, fut))
        if not fut["done"].wait(timeout=timeout):
            raise TimeoutError("browser command timed out")
        if fut["error"]:
            raise RuntimeError(fut["error"])
        return fut["result"]

    # -- actions -----------------------------------------------------------

    def open_url(self, url: str) -> dict:
        def _do(page):
            page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            return {"title": page.title(), "url": page.url}
        return self._call(_do)

    def play_youtube(self, query: str, fullscreen: Optional[bool] = None) -> dict:
        q = urllib.parse.quote_plus(query)
        want_fs = self.fullscreen if fullscreen is None else fullscreen

        def _do(page):
            page.goto(f"https://www.youtube.com/results?search_query={q}",
                      wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            _dismiss_consent(page)
            page.wait_for_selector("a#video-title", timeout=15_000)
            link = page.query_selector("a#video-title")
            href = link.get_attribute("href") if link else None
            title = (link.get_attribute("title") or link.inner_text()).strip() if link else ""
            if not href:
                raise RuntimeError("no video results found")
            watch = href if href.startswith("http") else "https://www.youtube.com" + href
            page.goto(watch, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            page.wait_for_selector("video", timeout=15_000)
            page.evaluate("() => { const v=document.querySelector('video'); if(v){v.muted=false; v.play();} }")
            if want_fs:
                _go_fullscreen(page)
            return {"title": title or page.title(), "url": page.url}
        return self._call(_do, timeout=90)

    def play_youtube_music(self, query: str) -> dict:
        q = urllib.parse.quote_plus(query)

        def _do(page):
            page.goto(f"https://music.youtube.com/search?q={q}",
                      wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            _dismiss_consent(page)
            # The search page is a heavy SPA; rather than chase click targets, take
            # the first track's watch link and open it directly in the YTM player.
            # The track links are zero-size anchors (not "visible"), so wait for
            # them to be attached rather than visible, then read the href + label.
            page.wait_for_selector('a[href*="watch?v="]', state="attached", timeout=20_000)
            link = page.query_selector('a[href*="watch?v="]')
            href = link.get_attribute("href") if link else None
            title = (link.get_attribute("aria-label") or "").strip() if link else ""
            if not href:
                raise RuntimeError("no songs found")
            watch = href if href.startswith("http") else "https://music.youtube.com/" + href.lstrip("/")
            page.goto(watch, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            page.wait_for_selector("video", timeout=20_000)
            page.evaluate("() => { const v=document.querySelector('video'); if(v){v.muted=false; v.play();} }")
            page.wait_for_timeout(800)
            bar = page.evaluate(
                "() => { const t=document.querySelector('ytmusic-player-bar .title');"
                " return t ? t.textContent.trim() : ''; }"
            )
            return {"title": bar or title or page.title(), "url": page.url}
        return self._call(_do, timeout=90)

    def media(self, action: str, seconds: float = 0.0) -> dict:
        return self._call(lambda page: page.evaluate(_MEDIA_JS, [action, seconds]))

    def fullscreen(self) -> dict:
        def _do(page):
            _go_fullscreen(page)
            return {"fullscreen": True}
        return self._call(_do)

    def status(self) -> dict:
        return self._call(lambda page: page.evaluate(_STATUS_JS))

    def close(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._cmd_q.put(None)


def _go_fullscreen(page) -> None:
    """Put the player into fullscreen. Clicking the player's fullscreen button is a
    real user gesture (more reliable than the 'f' hotkey alone)."""
    for sel in (".ytp-fullscreen-button", "#player .ytp-fullscreen-button"):
        try:
            btn = page.query_selector(sel)
            if btn:
                btn.click()
                return
        except Exception:  # noqa: BLE001
            continue
    try:
        page.keyboard.press("f")
    except Exception:  # noqa: BLE001
        pass


def _dismiss_consent(page) -> None:
    """Best-effort dismissal of the EU consent interstitial (YouTube / YT Music)."""
    for sel in ('button[aria-label*="Accept"]', 'button[aria-label*="Reject"]',
                'form[action*="consent"] button', 'tp-yt-paper-button[aria-label*="Accept"]'):
        try:
            btn = page.query_selector(sel)
            if btn:
                btn.click()
                return
        except Exception:  # noqa: BLE001
            continue
