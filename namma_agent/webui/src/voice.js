// Phase 9: OS-native voice from the web UI.
//
// Dictation records the microphone as 16 kHz mono PCM WAV and sends it to the
// server, which transcribes it with the operating system's own engine
// (Windows SAPI) or the configured cloud endpoint. Read-aloud asks the server
// for a WAV in a system voice and plays it. Either falls back to the browser's
// Web Speech API when the server has no engine or the user picked "Browser"
// (Settings → Behavior → Voice).
import { getAuthToken } from "./api.js";

let statusPromise = null;
export function voiceStatus(refresh = false) {
  if (!statusPromise || refresh) {
    statusPromise = fetch("/api/voice", { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
  }
  return statusPromise;
}

// Settings changed a voice preference: apply it now (the server copy saves
// in the background), so the next read-aloud / dictation uses it.
export function setVoicePrefs(patch) {
  statusPromise = (statusPromise || voiceStatus()).then((st) => st && ({ ...st, prefs: { ...(st.prefs || {}), ...patch } }));
}

function authHeaders(extra = {}) {
  const t = getAuthToken();
  return t ? { ...extra, "X-Namma-Token": t } : extra;
}

const browserSttCtor = () => (typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition)) || null;
export const browserTtsSupported = () => typeof window !== "undefined" && "speechSynthesis" in window;

// Which engine dictation should use: "server" or "browser" (or null = none).
export async function dictationEngine() {
  const st = await voiceStatus();
  const pref = st?.prefs?.stt_engine || "auto";
  const serverOk = !!(st?.stt?.system || st?.stt?.cloud);
  const micOk = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  if (pref === "browser") return browserSttCtor() ? "browser" : (serverOk && micOk ? "server" : null);
  if (serverOk && micOk) return "server";
  return browserSttCtor() ? "browser" : null;
}

// Which engine read-aloud should use: "server" or "browser" (or null).
export async function speechEngine() {
  const st = await voiceStatus();
  const pref = st?.prefs?.tts_engine || "auto";
  if (pref === "browser") return browserTtsSupported() ? "browser" : (st?.tts?.system ? "server" : null);
  if (st?.tts?.system) return "server";
  return browserTtsSupported() ? "browser" : null;
}

// ── WAV encoding ──────────────────────────────────────────────────────────

export function downsample(input, fromRate, toRate = 16000) {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    // Average the source samples that fold into this one (cheap low-pass).
    const start = Math.floor(i * ratio), end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

export function encodeWav(samples, sampleRate = 16000) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

// ── dictation ─────────────────────────────────────────────────────────────

// Start recording the microphone. Returns { stop(): Promise<Blob WAV>, cancel() }.
export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const source = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  proc.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  source.connect(proc);
  proc.connect(ctx.destination);
  const cleanup = () => {
    try { proc.disconnect(); source.disconnect(); } catch { /* already gone */ }
    stream.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => {});
  };
  return {
    async stop() {
      cleanup();
      const total = chunks.reduce((n, c) => n + c.length, 0);
      const all = new Float32Array(total);
      let at = 0;
      for (const c of chunks) { all.set(c, at); at += c.length; }
      return encodeWav(downsample(all, ctx.sampleRate, 16000), 16000);
    },
    cancel: cleanup,
  };
}

// Send a WAV to the server's dictation engine. Resolves { text, engine }.
export async function transcribe(wavBlob) {
  const r = await fetch("/api/voice/stt", {
    method: "POST", body: wavBlob, headers: authHeaders({ "Content-Type": "audio/wav" }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body?.detail || "Dictation failed.");
  return body;
}

// The browser's own recognizer (fallback). Returns { stop() }.
export function startBrowserDictation({ onText, onEnd, lang = navigator.language || "en-US" }) {
  const SR = browserSttCtor();
  const rec = new SR();
  rec.lang = lang;
  rec.interimResults = false;
  rec.onresult = (e) => onText(e.results[0][0].transcript);
  rec.onend = () => onEnd?.();
  rec.onerror = () => onEnd?.();
  rec.start();
  return { stop: () => rec.stop() };
}

// ── read-aloud ────────────────────────────────────────────────────────────

// Strip markdown so the voice reads words, not symbols.
export function toPlainText(md) {
  return (md || "")
    .replace(/```[\s\S]*?```/g, ". code block. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/[*_>#]/g, "")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
}

let current = null; // the one utterance playing app-wide

export function stopSpeaking() {
  if (current) { current.stop(); current = null; }
  if (browserTtsSupported()) window.speechSynthesis.cancel();
}

// Speak markdown text. Resolves when playback ends (or is stopped).
export async function speak(text, { onEnd } = {}) {
  stopSpeaking();
  const plain = toPlainText(text);
  if (!plain) { onEnd?.(); return; }
  const engine = await speechEngine();
  if (engine === "server") {
    try {
      const r = await fetch("/api/voice/tts", {
        method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ text: plain }),
      });
      if (r.ok) {
        const url = URL.createObjectURL(await r.blob());
        const audio = new Audio(url);
        const done = () => { URL.revokeObjectURL(url); if (current?.audio === audio) current = null; onEnd?.(); };
        audio.onended = done;
        audio.onerror = done;
        current = { audio, stop: () => { audio.pause(); done(); } };
        await audio.play();
        return;
      }
    } catch { /* fall through to the browser voice */ }
  }
  if (!browserTtsSupported()) { onEnd?.(); return; }
  const u = new SpeechSynthesisUtterance(plain);
  u.rate = 1.02;
  u.onend = () => onEnd?.();
  u.onerror = () => onEnd?.();
  current = { stop: () => { window.speechSynthesis.cancel(); onEnd?.(); } };
  window.speechSynthesis.speak(u);
}
