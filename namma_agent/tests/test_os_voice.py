"""Phase 9 — OS-native voice (read-aloud + dictation). Offline: every engine
call is mocked; no audio device, PowerShell or speech engine is needed."""
from __future__ import annotations

import subprocess
import types

import pytest
from fastapi.testclient import TestClient

from namma_agent.core import os_voice

WAV = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40


@pytest.fixture(autouse=True)
def _fresh():
    os_voice.reset_cache()
    yield
    os_voice.reset_cache()


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


def test_is_wav():
    assert os_voice.is_wav(WAV)
    assert not os_voice.is_wav(b"OggS" + b"\x00" * 60)
    assert not os_voice.is_wav(b"RIFF")


def test_windows_voices_parsed(monkeypatch):
    monkeypatch.setattr(os_voice, "_system", lambda: "Windows")
    monkeypatch.setattr(os_voice, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(os_voice, "_run_ps", lambda *a, **k: _cp(out="Microsoft Zira Desktop|en-US|Female\n\n"))
    assert os_voice.tts_engine() == "windows-sapi"
    assert os_voice.list_voices() == [{"id": "Microsoft Zira Desktop", "name": "Microsoft Zira Desktop",
                                       "lang": "en-US", "gender": "Female"}]


def test_windows_tts_passes_text_and_paths_via_env_not_script(monkeypatch, tmp_path):
    monkeypatch.setattr(os_voice, "_system", lambda: "Windows")
    monkeypatch.setattr(os_voice, "_powershell", lambda: "powershell.exe")
    seen = {}

    def fake_ps(script, env, timeout=0):
        seen["script"], seen["env"] = script, env
        with open(env["NAMMA_TTS_IN"], encoding="utf-8") as fh:
            seen["text"] = fh.read()
        with open(env["NAMMA_TTS_OUT"], "wb") as fh:
            fh.write(WAV)
        return _cp()

    monkeypatch.setattr(os_voice, "_run_ps", fake_ps)
    evil = "'; Remove-Item C:\\ -Recurse; '"
    assert os_voice.synthesize(evil, voice="Zira", rate=40) == WAV
    assert evil not in seen["script"]            # never interpolated into PowerShell
    assert seen["text"] == evil
    assert seen["env"]["NAMMA_TTS_VOICE"] == "Zira"
    assert seen["env"]["NAMMA_TTS_RATE"] == "10"  # clamped to SAPI's -10..10


def test_tts_errors_are_clear(monkeypatch):
    monkeypatch.setattr(os_voice, "_system", lambda: "Linux")
    monkeypatch.setattr(os_voice, "_linux_tts_binary", lambda: None)
    with pytest.raises(os_voice.VoiceError, match="espeak-ng"):
        os_voice.synthesize("hello")
    with pytest.raises(os_voice.VoiceError, match="Nothing"):
        os_voice.synthesize("   ")


def test_macos_say_command(monkeypatch):
    monkeypatch.setattr(os_voice, "_system", lambda: "Darwin")
    monkeypatch.setattr(os_voice.shutil, "which", lambda name: "/usr/bin/say" if name == "say" else None)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = cmd[cmd.index("-o") + 1]
        with open(out, "wb") as fh:
            fh.write(WAV)
        return _cp()

    monkeypatch.setattr(os_voice.subprocess, "run", fake_run)
    assert os_voice.synthesize("hi", voice="Samantha") == WAV
    assert calls[0][0] == "say" and "-v" in calls[0] and "Samantha" in calls[0]


def test_transcribe_uses_system_then_cloud(monkeypatch):
    monkeypatch.setattr(os_voice, "stt_engine", lambda: "windows-sapi")
    monkeypatch.setattr(os_voice, "_transcribe_sapi", lambda wav, lang="": "hello world")
    assert os_voice.transcribe(WAV) == {"text": "hello world", "engine": "windows-sapi"}

    monkeypatch.setattr(os_voice, "stt_engine", lambda: None)
    monkeypatch.setattr(os_voice, "cloud_stt_configured", lambda config=None: True)
    monkeypatch.setattr(os_voice, "_transcribe_cloud", lambda wav: "from the cloud")
    assert os_voice.transcribe(WAV)["engine"] == "cloud"
    with pytest.raises(os_voice.VoiceError, match="no built-in dictation"):
        os_voice.transcribe(WAV, engine="system")


def test_transcribe_rejects_bad_input(monkeypatch):
    with pytest.raises(os_voice.VoiceError, match="No audio"):
        os_voice.transcribe(b"")
    with pytest.raises(os_voice.VoiceError, match="WAV"):
        os_voice.transcribe(b"OggS" + b"\x00" * 100)
    with pytest.raises(os_voice.VoiceError, match="too long"):
        os_voice.transcribe(b"RIFF" + b"\x00" * (os_voice.MAX_STT_BYTES + 1))


def test_sapi_without_recognizer(monkeypatch):
    monkeypatch.setattr(os_voice, "_run_ps", lambda *a, **k: _cp(rc=3, err="no-recognizer"))
    with pytest.raises(os_voice.VoiceError, match="speech recognizer"):
        os_voice._transcribe_sapi(WAV)


# -- endpoints -----------------------------------------------------------------

def _client(monkeypatch):
    from namma_agent.server.api import create_app

    svc = types.SimpleNamespace(config={"voice": {"tts_voice": "Zira", "stt_engine": "auto"}})
    import namma_agent.server.api as api_mod
    # create_app needs a real service; build one cheaply.
    from namma_agent.core.memory import Database
    from namma_agent.core.providers.base import LLMResponse, Provider
    from namma_agent.core.tools import ToolRegistry
    from namma_agent.service import NammaAgentService

    class P(Provider):
        name = "scripted"

        def __init__(self):
            super().__init__(model="scripted")

        def is_available(self):
            return True

        def generate(self, *a, **k):
            return LLMResponse(content="hi")

    real = NammaAgentService(config={"persona": "core", "conversation": {}, "voice": svc.config["voice"]},
                             provider=P(), registry=ToolRegistry(), db=Database(":memory:"))
    assert api_mod  # imported for monkeypatch scope
    return TestClient(create_app(real))


def test_tts_endpoint_returns_wav(monkeypatch):
    seen = {}

    def fake_synth(text, voice="", rate=0):
        seen.update(text=text, voice=voice)
        return WAV

    monkeypatch.setattr(os_voice, "synthesize", fake_synth)
    r = _client(monkeypatch).post("/api/voice/tts", json={"text": "hello"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content == WAV
    assert seen == {"text": "hello", "voice": "Zira"}   # falls back to the saved voice


def test_tts_endpoint_maps_errors_to_422(monkeypatch):
    def boom(*a, **k):
        raise os_voice.VoiceError("No system voice found.")

    monkeypatch.setattr(os_voice, "synthesize", boom)
    r = _client(monkeypatch).post("/api/voice/tts", json={"text": "hello"})
    assert r.status_code == 422 and "No system voice" in r.json()["detail"]


def test_stt_endpoint(monkeypatch):
    monkeypatch.setattr(os_voice, "transcribe", lambda wav, engine="auto", language="": {"text": "dictated", "engine": engine})
    c = _client(monkeypatch)
    r = c.post("/api/voice/stt", content=WAV, headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json() == {"text": "dictated", "engine": "auto"}
    r = c.post("/api/voice/stt?engine=cloud", content=WAV)
    assert r.json()["engine"] == "cloud"


def test_stt_endpoint_caps_size(monkeypatch):
    monkeypatch.setattr(os_voice, "MAX_STT_BYTES", 100)
    r = _client(monkeypatch).post("/api/voice/stt", content=b"RIFF" + b"\x00" * 200)
    assert r.status_code == 413


def test_status_endpoint(monkeypatch):
    monkeypatch.setattr(os_voice, "tts_engine", lambda: "windows-sapi")
    monkeypatch.setattr(os_voice, "list_voices", lambda: [{"id": "Zira", "name": "Zira", "lang": "en-US", "gender": "Female"}])
    monkeypatch.setattr(os_voice, "stt_engine", lambda: "windows-sapi")
    monkeypatch.setattr(os_voice, "cloud_stt_configured", lambda config=None: False)
    body = _client(monkeypatch).get("/api/voice").json()
    assert body["tts"]["system"] and body["stt"]["engine"] == "windows-sapi"
    assert body["prefs"]["tts_voice"] == "Zira" and body["prefs"]["stt_engine"] == "auto"
