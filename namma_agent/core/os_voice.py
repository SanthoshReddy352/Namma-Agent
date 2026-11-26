"""OS-native speech: read-aloud (TTS) and dictation (STT) through the operating
system's own speech engines instead of the browser's Web Speech API.

Why: the browser's dictation only works well in Chrome (it streams audio to
Google) and does not work at all inside the Electron/WebView2 desktop shell,
and browser voices vary per browser. The OS engines are local, offline and the
same voices the rest of the system uses.

Engines:
  * Windows — System.Speech (SAPI 5) via Windows PowerShell 5.1, built in:
      TTS: SpeechSynthesizer → WAV, every installed voice;
      STT: SpeechRecognitionEngine + DictationGrammar over a WAV file.
  * macOS — ``say`` (TTS). No built-in command-line dictation.
  * Linux — ``espeak-ng`` / ``espeak`` (TTS). No built-in dictation.

When the OS has no dictation engine, ``transcribe`` falls back to the
configured OpenAI-compatible transcription endpoint (``comms.stt``), and the
web UI falls back to the browser. Nothing here raises for a missing engine:
callers get a ``VoiceError`` with a clear "install X" message.

User text and file paths reach PowerShell only through environment variables
and temp files — never interpolated into the script.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from typing import Optional

from namma_agent.core.logger import logger

MAX_TTS_CHARS = 6000
MAX_STT_BYTES = 12 * 1024 * 1024  # ~6 min of 16 kHz mono PCM
_TIMEOUT_S = 90


class VoiceError(RuntimeError):
    """A speech request that can't be served (missing engine, bad input…)."""


def _system() -> str:
    return platform.system()


def _powershell() -> Optional[str]:
    return shutil.which("powershell") or shutil.which("powershell.exe")


def _run_ps(script: str, env_extra: dict, timeout: int = _TIMEOUT_S) -> subprocess.CompletedProcess:
    exe = _powershell()
    if not exe:
        raise VoiceError("Windows PowerShell was not found, so the system speech engine can't run.")
    env = {**os.environ, **env_extra}
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env, **kwargs)


_PS_PRELUDE = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; "

_PS_VOICES = _PS_PRELUDE + (
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { "
    "$_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name + '|' + $_.VoiceInfo.Gender }; "
    "$s.Dispose()")

_PS_TTS = _PS_PRELUDE + (
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "if ($env:NAMMA_TTS_VOICE) { try { $s.SelectVoice($env:NAMMA_TTS_VOICE) } catch { } }; "
    "$s.Rate = [int]$env:NAMMA_TTS_RATE; "
    "$s.SetOutputToWaveFile($env:NAMMA_TTS_OUT); "
    "$s.Speak([IO.File]::ReadAllText($env:NAMMA_TTS_IN, [Text.Encoding]::UTF8)); "
    "$s.Dispose()")

_PS_STT_CHECK = _PS_PRELUDE + (
    "$r = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers(); "
    "$r | ForEach-Object { $_.Culture.Name }")

# Recognise a whole WAV file: Recognize() returns one phrase at a time; stop
# when the audio position stops advancing (end of the file).
_PS_STT = _PS_PRELUDE + (
    "$recs = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers(); "
    "if (-not $recs) { [Console]::Error.WriteLine('no-recognizer'); exit 3 }; "
    "$want = $env:NAMMA_STT_LANG; "
    "$ri = $recs | Where-Object { $_.Culture.Name -eq $want } | Select-Object -First 1; "
    "if (-not $ri) { $ri = $recs | Where-Object { $_.Culture.Name -eq [Globalization.CultureInfo]::CurrentUICulture.Name } | Select-Object -First 1 }; "
    "if (-not $ri) { $ri = $recs[0] }; "
    "$e = New-Object System.Speech.Recognition.SpeechRecognitionEngine($ri); "
    "$e.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
    "$e.SetInputToWaveFile($env:NAMMA_STT_IN); "
    "$out = New-Object System.Collections.Generic.List[string]; $prev = -1; "
    "while ($true) { "
    "  try { $res = $e.Recognize() } catch { break }; "
    "  if ($res) { $out.Add($res.Text) }; "
    "  $pos = $e.AudioPosition.TotalMilliseconds; "
    "  if ($pos -le $prev) { break }; $prev = $pos "
    "}; "
    "$e.Dispose(); "
    "Write-Output ($out -join ' ')")


# ── capability probes ─────────────────────────────────────────────────────

_cache: dict = {}


def _linux_tts_binary() -> Optional[str]:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def tts_engine() -> Optional[str]:
    sysname = _system()
    if sysname == "Windows":
        return "windows-sapi" if _powershell() else None
    if sysname == "Darwin":
        return "macos-say" if shutil.which("say") else None
    if sysname == "Linux":
        b = _linux_tts_binary()
        return os.path.basename(b) if b else None
    return None


def list_voices() -> list[dict]:
    """Installed system voices: [{id, name, lang, gender}] (cached)."""
    if "voices" in _cache:
        return _cache["voices"]
    voices: list[dict] = []
    engine = tts_engine()
    try:
        if engine == "windows-sapi":
            cp = _run_ps(_PS_VOICES, {}, timeout=30)
            for line in (cp.stdout or "").splitlines():
                parts = line.strip().split("|")
                if len(parts) >= 2 and parts[0]:
                    voices.append({"id": parts[0], "name": parts[0], "lang": parts[1],
                                   "gender": parts[2] if len(parts) > 2 else ""})
        elif engine == "macos-say":
            cp = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=20)
            for line in (cp.stdout or "").splitlines():
                head = line.split("#", 1)[0].rstrip()
                bits = head.rsplit(None, 1)
                if len(bits) == 2:
                    voices.append({"id": bits[0].strip(), "name": bits[0].strip(), "lang": bits[1], "gender": ""})
        elif engine in ("espeak-ng", "espeak"):
            cp = subprocess.run([_linux_tts_binary(), "--voices"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=20)
            for line in (cp.stdout or "").splitlines()[1:]:
                cols = line.split()
                if len(cols) >= 4:
                    voices.append({"id": cols[4] if len(cols) > 4 else cols[3], "name": cols[3],
                                   "lang": cols[1], "gender": cols[2]})
    except (OSError, subprocess.SubprocessError, VoiceError) as exc:
        logger.info("[voice] listing system voices failed: %s", exc)
    _cache["voices"] = voices
    return voices


def stt_engine() -> Optional[str]:
    """'windows-sapi' when a SAPI dictation recognizer is installed, else None."""
    if "stt" in _cache:
        return _cache["stt"]
    engine = None
    if _system() == "Windows" and _powershell():
        try:
            cp = _run_ps(_PS_STT_CHECK, {}, timeout=30)
            if (cp.stdout or "").strip():
                engine = "windows-sapi"
        except (OSError, subprocess.SubprocessError, VoiceError) as exc:
            logger.info("[voice] probing system dictation failed: %s", exc)
    _cache["stt"] = engine
    return engine


def cloud_stt_configured(config: Optional[dict] = None) -> bool:
    from namma_agent.config import load_config

    cfg = ((config or load_config()).get("comms") or {}).get("stt") or {}
    return bool(os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"), ""))


def status(config: Optional[dict] = None) -> dict:
    """What the web UI needs to choose engines and fill the voice picker."""
    from namma_agent.config import load_config

    cfg = config or load_config()
    prefs = cfg.get("voice") or {}
    tts = tts_engine()
    stt = stt_engine()
    return {
        "platform": _system(),
        "tts": {"system": bool(tts), "engine": tts, "voices": list_voices() if tts else []},
        "stt": {"system": bool(stt), "engine": stt, "cloud": cloud_stt_configured(cfg)},
        "prefs": {
            "tts_engine": prefs.get("tts_engine", "auto"),
            "tts_voice": prefs.get("tts_voice", ""),
            "tts_rate": int(prefs.get("tts_rate", 0) or 0),
            "stt_engine": prefs.get("stt_engine", "auto"),
            "stt_language": prefs.get("stt_language", ""),
        },
    }


# ── speech ────────────────────────────────────────────────────────────────

def synthesize(text: str, voice: str = "", rate: int = 0) -> bytes:
    """Speak ``text`` with the OS engine and return a WAV file's bytes."""
    text = (text or "").strip()
    if not text:
        raise VoiceError("Nothing to read aloud.")
    text = text[:MAX_TTS_CHARS]
    rate = max(-10, min(10, int(rate or 0)))
    engine = tts_engine()
    if not engine:
        raise VoiceError(_missing_tts_hint())
    with tempfile.TemporaryDirectory(prefix="namma-tts-") as tmp:
        src = os.path.join(tmp, "in.txt")
        out = os.path.join(tmp, "out.wav")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(text)
        if engine == "windows-sapi":
            cp = _run_ps(_PS_TTS, {"NAMMA_TTS_IN": src, "NAMMA_TTS_OUT": out,
                                   "NAMMA_TTS_VOICE": voice or "", "NAMMA_TTS_RATE": str(rate)})
        elif engine == "macos-say":
            cmd = ["say", "-o", out, "--data-format=LEI16@22050", "-f", src]
            if voice:
                cmd[1:1] = ["-v", voice]
            if rate:
                cmd[1:1] = ["-r", str(175 + rate * 15)]
            cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=_TIMEOUT_S)
        else:
            cmd = [_linux_tts_binary(), "-w", out, "-f", src, "-s", str(175 + rate * 15)]
            if voice:
                cmd[1:1] = ["-v", voice]
            cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=_TIMEOUT_S)
        if cp.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 44:
            logger.warning("[voice] TTS failed (%s): %s", engine, (cp.stderr or "")[:300])
            raise VoiceError("The system voice couldn't read that aloud.")
        with open(out, "rb") as fh:
            return fh.read()


def _missing_tts_hint() -> str:
    sysname = _system()
    if sysname == "Linux":
        return "No system voice found. Install espeak-ng (e.g. `sudo apt install espeak-ng`)."
    if sysname == "Windows":
        return "Windows PowerShell is missing, so the system voice can't run."
    return "This system has no voice engine the app can use."


def is_wav(data: bytes) -> bool:
    return len(data) > 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def transcribe(wav: bytes, engine: str = "auto", language: str = "") -> dict:
    """Dictation: WAV bytes → {"text", "engine"}.

    ``engine``: auto (system, then cloud) | system | cloud. Raises VoiceError
    when the chosen engine can't serve the request.
    """
    if not wav:
        raise VoiceError("No audio was received.")
    if len(wav) > MAX_STT_BYTES:
        raise VoiceError("That recording is too long. Keep dictation under about six minutes.")
    if not is_wav(wav):
        raise VoiceError("Dictation expects a WAV recording.")
    engine = (engine or "auto").lower()
    system_ok = stt_engine() is not None
    if engine in ("auto", "system") and system_ok:
        return {"text": _transcribe_sapi(wav, language), "engine": "windows-sapi"}
    if engine == "system":
        raise VoiceError("This computer has no built-in dictation engine. Choose Cloud or Browser in Settings → Voice.")
    if engine in ("auto", "cloud") and cloud_stt_configured():
        return {"text": _transcribe_cloud(wav), "engine": "cloud"}
    raise VoiceError("No dictation engine is available here. Add a transcription key (comms.stt) or use the browser's dictation.")


def _transcribe_sapi(wav: bytes, language: str = "") -> str:
    with tempfile.TemporaryDirectory(prefix="namma-stt-") as tmp:
        src = os.path.join(tmp, "in.wav")
        with open(src, "wb") as fh:
            fh.write(wav)
        cp = _run_ps(_PS_STT, {"NAMMA_STT_IN": src, "NAMMA_STT_LANG": language or ""})
        if cp.returncode == 3:
            raise VoiceError("Windows has no speech recognizer installed. Add one in Settings → Time & language → Speech.")
        if cp.returncode != 0:
            logger.warning("[voice] SAPI dictation failed: %s", (cp.stderr or "")[:300])
            raise VoiceError("Windows dictation couldn't process that recording.")
        return " ".join((cp.stdout or "").split())


def _transcribe_cloud(wav: bytes) -> str:
    from namma_agent.comms.transcribe import transcribe_audio

    with tempfile.TemporaryDirectory(prefix="namma-stt-") as tmp:
        src = os.path.join(tmp, "dictation.wav")
        with open(src, "wb") as fh:
            fh.write(wav)
        text = transcribe_audio(src)
    if text is None:
        raise VoiceError("The cloud transcription service didn't return any text.")
    return text.strip()


def reset_cache() -> None:
    """Forget probed engines/voices (tests; after installing a voice)."""
    _cache.clear()
