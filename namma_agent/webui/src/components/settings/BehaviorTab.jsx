// Settings → BehaviorTab (split out of Settings.jsx, Phase 9 W1).

import { Section, Field, Input, Select, Toggle } from "./shared.jsx";
import { useEffect, useState } from "react";
import { Skeleton } from "../ui/index.js";
import { setVoicePrefs, speak, voiceStatus } from "../../voice.js";
import { fetchAutostart, setAutostart } from "../../api.js";

// Phase 9: voice uses the operating system's own speech engines (Windows
// SAPI voices + dictation, macOS `say`, espeak-ng), with the browser's Web
// Speech API as a fallback or an explicit choice. Saves itself like the rest.
export function VoiceSettings({ cur, setC }) {
  const [st, setSt] = useState(null);
  const [testing, setTesting] = useState(false);
  useEffect(() => { voiceStatus(true).then(setSt); }, []);
  const set = (key, value) => { setC(`voice.${key}`, value); setVoicePrefs({ [key]: value }); };
  if (!st) return <Section title="Voice"><Skeleton lines={3} className="h-5 w-full" /></Section>;
  const voices = st.tts?.voices || [];
  const sttWhat = st.stt?.system ? "your system's speech recognition (offline)"
    : st.stt?.cloud ? "your cloud transcription service" : "the browser (Chrome works best)";
  const ttsWhat = st.tts?.system ? `${voices.length} system voice${voices.length === 1 ? "" : "s"} on this computer` : "the browser's voices";
  return (
    <Section title="Voice" hint={`Dictation uses ${sttWhat}. Read-aloud uses ${ttsWhat}.`}>
      <Field label="Read aloud with">
        <Select value={cur("voice.tts_engine", "auto")} onChange={(v) => set("tts_engine", v)}
                options={["auto", "system", "browser"]} />
      </Field>
      {st.tts?.system && (
        <Field label="System voice">
          <select value={cur("voice.tts_voice", "")} onChange={(e) => set("tts_voice", e.target.value)}
                  className="w-full rounded-lg border border-border bg-bg px-2 py-1.5 outline-none focus:border-brand">
            <option value="">System default</option>
            {voices.map((v) => <option key={v.id} value={v.id}>{v.name}{v.lang ? ` (${v.lang})` : ""}</option>)}
          </select>
        </Field>
      )}
      {st.tts?.system && (
        <Field label={`Speed (${cur("voice.tts_rate", 0)})`}>
          <input type="range" min="-5" max="5" step="1" value={cur("voice.tts_rate", 0)} aria-label="Reading speed"
                 onChange={(e) => set("tts_rate", parseInt(e.target.value, 10))} className="w-full" />
        </Field>
      )}
      <div className="flex justify-end">
        <button type="button" disabled={testing}
                onClick={() => { setTesting(true); speak(`Hello, this is how I sound.`, { onEnd: () => setTesting(false) }); }}
                className="px-3 py-1.5 rounded-lg border border-border text-sm hover:bg-surface-sunken disabled:opacity-50">
          {testing ? "Speaking…" : "Test voice"}
        </button>
      </div>
      <Field label="Dictate with">
        <Select value={cur("voice.stt_engine", "auto")} onChange={(v) => set("stt_engine", v)}
                options={["auto", "system", "cloud", "browser"]} />
      </Field>
      {!st.stt?.system && st.platform === "Windows" && (
        <div className="text-xs text-fg-muted">No Windows speech recognizer is installed. Add one in Windows Settings → Time &amp; language → Speech.</div>
      )}
    </Section>
  );
}

// Phase 5: start-on-login. Self-contained — reads/writes /api/autostart (the
// HKCU Run key on Windows, an XDG autostart entry on Linux), so it needs no
// place in config.yaml and applies instantly, no Save required.
export function AutostartToggle() {
  const [st, setSt] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { fetchAutostart().then(setSt).catch(() => setSt(null)); }, []);
  if (!st) return null;
  if (!st.supported) {
    return <div className="text-xs text-fg-subtle">
      Start on login isn't supported on {st.platform || "this OS"} yet.</div>;
  }
  const flip = async (v) => {
    setErr("");
    const r = await setAutostart(v).catch((e) => ({ ok: false, error: String(e) }));
    if (r?.ok) setSt((s) => ({ ...s, enabled: r.enabled }));
    else setErr(r?.error || "could not change start-on-login");
  };
  return (
    <>
      <Toggle label="Start when I sign in to this computer" checked={!!st.enabled} onChange={flip} />
      {err && <div className="text-xs text-red-500">{err}</div>}
    </>
  );
}

// Settings → Behavior: turn limits, model tuning, voice.
export function BehaviorTab({ form }) {
  const { data, cur, setC, env, setEnv, commitEnv } = form;
  return (
    <>
    <Section title="Behavior">
      <AutostartToggle />
      <Field label="Default mode"><Select value={cur("conversation.default_mode", "agent")} onChange={(v) => setC("conversation.default_mode", v)} options={["agent", "chat"]} /></Field>
      <Toggle label="Auto mode — run tools (incl. shell) without asking" checked={!!cur("conversation.auto_approve", false)} onChange={(v) => setC("conversation.auto_approve", v)} />
      <Field label="Tool step limit (0 = unlimited)"><Input type="number" value={cur("conversation.tool_loop_limit", 0)} onChange={(v) => setC("conversation.tool_loop_limit", parseInt(v || "0", 10))} /></Field>
      <Field label="Turn token budget (0 = off) — stop a turn before another tool round once it has used this many tokens"><Input type="number" value={cur("conversation.turn_token_budget", 0)} onChange={(v) => setC("conversation.turn_token_budget", parseInt(v || "0", 10))} /></Field>
      <Field label="History turns kept"><Input type="number" value={cur("conversation.max_history_turns", 12)} onChange={(v) => setC("conversation.max_history_turns", parseInt(v || "0", 10))} /></Field>
      <div className="pt-2 mt-1 border-t border-border" />
      <div className="text-xs text-fg-subtle">Model tuning (applies to every model)</div>
      <Field label="Max tokens"><Input type="number" value={cur("provider.max_tokens", 8192)} onChange={(v) => setC("provider.max_tokens", parseInt(v || "0", 10))} /></Field>
      <Field label={`Temperature (${cur("provider.temperature", 0.3)})`}>
        <input type="range" min="0" max="1" step="0.05" value={cur("provider.temperature", 0.3)}
               onChange={(e) => setC("provider.temperature", parseFloat(e.target.value))} className="w-full" />
      </Field>
      <Field label="Timeout (s)"><Input type="number" value={cur("provider.timeout_s", 60)} onChange={(v) => setC("provider.timeout_s", parseInt(v || "0", 10))} /></Field>
    </Section>
    <VoiceSettings cur={cur} setC={setC} />
    </>
  );
}

// Settings → Browser: which browser the agent drives, and how.
export function BrowserTab({ form }) {
  const { data, cur, setC, env, setEnv, commitEnv } = form;
  return (
    <Section title="Browser & media">
      <Field label="Preferred browser"><Select value={cur("browser.preferred", "auto")} onChange={(v) => setC("browser.preferred", v)} options={["auto", "chrome", "chromium", "brave", "edge", "vivaldi", "opera", "firefox"]} /></Field>
      <Toggle label="Reuse my real browser profile (sign-ins)" checked={!!cur("browser.use_system_profile", true)} onChange={(v) => setC("browser.use_system_profile", v)} />
      <Toggle label="Open videos fullscreen" checked={!!cur("browser.fullscreen", true)} onChange={(v) => setC("browser.fullscreen", v)} />
      <Toggle label="Headless (no visible window)" checked={!!cur("browser.headless", false)} onChange={(v) => setC("browser.headless", v)} />
    </Section>
  );
}
