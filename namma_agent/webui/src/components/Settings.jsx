import { useEffect, useState } from "react";
import { applyUpdate, checkUpdate, clearMemory, deletePersona, exportPack, fetchCommsStatus, fetchConfiguredModels, fetchConfiguredProviders, fetchEnvStatus, fetchModels, fetchModelsForProvider, fetchPackItems, fetchPersona, fetchPersonas, fetchProviders, fetchSettings, fetchVersion, generatePersona, inspectPack, installPack, listSkills, listTools, packDownloadUrl, savePersona, saveConfiguredModels, saveConfiguredProviders, saveSettings, setPersona, startComms, stopComms, toggleSkill, toggleTool, toggleToolset, uninstallApp } from "../api.js";
import { COMPLETION_PRESETS, SOUND_EVENTS, completionPreset, previewPreset, setCompletionPreset, setSoundEventEnabled, setSoundVolume, setSoundsEnabled, soundEventEnabled, soundVolume, soundsEnabled } from "../sounds.js";
import { NOTIFY_EVENTS, notifyEnabled, notifyEventEnabled, sendTestNotification, setNotifyEnabled, setNotifyEventEnabled } from "../notify.js";

// Suggest an .env variable name for a provider's key. ONLY the native providers
// (OpenAI/Anthropic/Google) use their conventional shared var; every OpenAI-
// compatible endpoint (opencode, groq, ollama, custom…) gets a DISTINCT var
// derived from its label — otherwise they'd all collide on OPENAI_API_KEY (the
// exact bug that put a Groq key into OPENAI_API_KEY).
function suggestKeyEnv(type, label, catalog) {
  if (["openai", "anthropic", "google", "gemini"].includes(type)) {
    const c = (catalog || []).find((p) => p.type === type);
    if (c?.key_env) return c.key_env;
  }
  const slug = (label || type || "").toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "");
  return slug ? `${slug}_API_KEY` : "";
}

const get = (o, path, d) => path.split(".").reduce((x, k) => (x == null ? x : x[k]), o) ?? d;
function nest(path, value) {
  const out = {}; let cur = out; const ks = path.split(".");
  ks.forEach((k, i) => { if (i === ks.length - 1) cur[k] = value; else cur = cur[k] = {}; });
  return out;
}
function deepMerge(a, b) {
  for (const k in b) {
    if (b[k] && typeof b[k] === "object" && !Array.isArray(b[k])) a[k] = deepMerge(a[k] || {}, b[k]);
    else a[k] = b[k];
  }
  return a;
}

// Hermes-style grouped settings nav: labelled sections, each an icon + label row.
// (The Voice tab was folded into Behavior; the Phase-5 Sounds tab merged into the
// new Notifications panel alongside desktop notifications.)
const TAB_GROUPS = [
  { label: "General", tabs: ["Behavior", "Persona", "Appearance", "Notifications"] },
  { label: "Intelligence", tabs: ["Providers", "Models"] },
  { label: "Capabilities", tabs: ["Skills", "Toolsets", "Packs", "Browser"] },
  { label: "Channels", tabs: ["Messaging"] },
  { label: "System", tabs: ["Memory", "About"] },
];
const TABS = TAB_GROUPS.flatMap((g) => g.tabs);

// Compact 24×24 stroke icons (one per tab), drawn in currentColor.
const TAB_ICONS = {
  Behavior: "M4 6h16M4 12h10M4 18h7",
  Persona: "M12 12a4 4 0 100-8 4 4 0 000 8zM5 20a7 7 0 0114 0",
  Appearance: "M12 3a9 9 0 100 18h2a3 3 0 003-3 2 2 0 00-2-2h-1a2 2 0 010-4h2a3 3 0 003-3 9 9 0 00-9-6zM7.5 11a.5.5 0 100-1 .5.5 0 000 1zM10.5 7.5a.5.5 0 100-1 .5.5 0 000 1z",
  Notifications: "M6 8a6 6 0 1112 0c0 5 2 6 2 6H4s2-1 2-6M10 20a2 2 0 004 0",
  Providers: "M4 7a8 4 0 0016 0 8 4 0 00-16 0v10a8 4 0 0016 0V7",
  Models: "M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3M7 7h10v10H7z",
  Skills: "M12 3l2.5 5 5.5.8-4 3.9.9 5.5L12 21l-4.9-2.8.9-5.5-4-3.9 5.5-.8z",
  Toolsets: "M14.5 5.5a3.5 3.5 0 01-4.6 4.6L5 15l4 4 4.9-4.9a3.5 3.5 0 014.6-4.6l-1.8 1.8-2.1-.3-.3-2.1z",
  Packs: "M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8",
  Browser: "M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c2.5 2.5 4 5.7 4 9s-1.5 6.5-4 9c-2.5-2.5-4-5.7-4-9s1.5-6.5 4-9z",
  Messaging: "M4 5h16v11H8l-4 4z",
  Memory: "M4 7a8 4 0 0016 0 8 4 0 00-16 0v10a8 4 0 0016 0M4 12a8 4 0 0016 0",
  About: "M12 3a9 9 0 100 18 9 9 0 000-18zM12 11v5M12 7.5h.01",
};
function TabIcon({ name }) {
  const d = TAB_ICONS[name];
  if (!d) return null;
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="shrink-0"
         stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

// The four named palettes (must mirror the theme blocks in src/index.css). The
// swatch colors are just for the picker preview.
const THEMES = [
  { id: "default", label: "Default", swatch: ["#2f6bff", "#f6f8fc", "#10131a"] },
  { id: "slate", label: "Slate", swatch: ["#3d6094", "#f4f6f9", "#1b2230"] },
  { id: "classic", label: "Classic", swatch: ["#cc785c", "#faf9f5", "#2d2a26"] },
  { id: "mono", label: "Mono", swatch: ["#3f3f46", "#fafafa", "#171717"] },
];

function ThemePicker({ themeName, onThemeNameChange }) {
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
      {THEMES.map((t) => {
        const active = themeName === t.id;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onThemeNameChange(t.id)}
            className={
              "rounded-xl border p-2.5 text-left transition " +
              (active
                ? "border-brand ring-2 ring-brand/30"
                : "border-line dark:border-night-line hover:border-brand/50")
            }
          >
            <div className="flex gap-1">
              {t.swatch.map((c, i) => (
                <span key={i} className="h-6 flex-1 rounded" style={{ background: c }} />
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-[13px] font-medium text-ink dark:text-night-ink">{t.label}</span>
              {active && (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-brand">
                  <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// About / Updates / Danger-zone (uninstall) — mirrors Hermes' Settings → About.
function AboutTab() {
  const [version, setVersion] = useState("");
  const [upd, setUpd] = useState(null);
  const [updating, setUpdating] = useState(false);
  const [confirm, setConfirm] = useState(null); // {scope, label}
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetchVersion().then((r) => setVersion(r?.version || "")).catch(() => {});
    checkUpdate().then(setUpd).catch(() => {});
  }, []);

  const doUpdate = async () => {
    setUpdating(true);
    await applyUpdate().catch(() => {});
    setMsg("Updating… the app will relaunch shortly.");
  };

  const doUninstall = async () => {
    setBusy(true);
    const r = await uninstallApp(confirm.scope).catch((e) => ({ started: false, error: String(e) }));
    if (r?.started) {
      setMsg("Uninstalling… this window will close in a moment.");
    } else {
      setMsg("Could not start the uninstaller: " + (r?.error || "unknown error"));
      setBusy(false);
      setConfirm(null);
    }
  };

  const RED = "#dc2626";
  return (
    <>
      <Section title="About">
        <div className="text-[14px] font-medium text-ink dark:text-night-ink">Namma Agent</div>
        <div className="text-[13px] text-ink-soft dark:text-night-faint">Version {version || "…"}</div>
      </Section>

      <Section title="Updates" hint="Pull the latest version and relaunch automatically.">
        {upd?.update_available ? (
          <button onClick={doUpdate} disabled={updating}
                  className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50">
            {updating ? "Updating…" : `Update to ${upd.latest}`}
          </button>
        ) : (
          <div className="text-[13px] text-ink-soft dark:text-night-faint">
            {upd ? "You’re on the latest version." : "Checking for updates…"}
          </div>
        )}
      </Section>

      <Section title="Danger zone" hint="Remove Namma Agent from this computer.">
        <div className="flex flex-wrap gap-2">
          <button onClick={() => { setConfirm({ scope: "keep-data", label: "Uninstall, keep my data" }); setTyped(""); setMsg(""); }}
                  className="px-3 py-1.5 rounded-lg border hover:bg-[#dc2626]/10"
                  style={{ borderColor: RED + "66", color: RED }}>Uninstall, keep my data</button>
          <button onClick={() => { setConfirm({ scope: "all", label: "Uninstall everything" }); setTyped(""); setMsg(""); }}
                  className="px-3 py-1.5 rounded-lg text-white hover:opacity-90"
                  style={{ background: RED }}>Uninstall everything</button>
        </div>
        {msg && <div className="mt-2 text-[13px] text-ink-soft dark:text-night-faint">{msg}</div>}
      </Section>

      {confirm && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 p-4">
          <div className="w-[440px] max-w-full rounded-2xl bg-paper-panel dark:bg-night-panel p-6 shadow-pop animate-rise">
            <h3 className="text-[17px] font-semibold text-ink dark:text-night-ink">{confirm.label}</h3>
            <p className="mt-2 text-[13.5px] leading-relaxed text-ink-soft dark:text-night-faint">
              {confirm.scope === "all"
                ? "This permanently deletes the app AND all your chats, settings, and data. This cannot be undone."
                : "This removes the app, but first backs up your chats & settings to your user folder so you can restore them later."}
            </p>
            <p className="mt-3 text-[13px] text-ink-soft dark:text-night-faint">Type <b>UNINSTALL</b> to confirm:</p>
            <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)}
                   className="mt-1 w-full rounded-lg border border-line dark:border-night-line bg-transparent px-3 py-2 outline-none focus:border-brand text-ink dark:text-night-ink" />
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setConfirm(null)} disabled={busy}
                      className="px-4 py-2 rounded-lg text-ink-soft dark:text-night-ink hover:bg-paper-soft dark:hover:bg-night-soft">Cancel</button>
              <button onClick={doUninstall} disabled={busy || typed.trim().toUpperCase() !== "UNINSTALL"}
                      className="px-4 py-2 rounded-lg text-white hover:opacity-90 disabled:opacity-40"
                      style={{ background: RED }}>{busy ? "Uninstalling…" : "Uninstall"}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default function Settings({ onClose, theme, onThemeToggle, themeName, onThemeNameChange, onMemoryCleared, onModelsChanged, onAssistantNameChanged }) {
  const [tab, setTab] = useState("Behavior");
  const [data, setData] = useState(null);
  const [providers, setProviders] = useState([]);  // catalog of provider TYPES
  const [cfg, setCfg] = useState({});
  const [env, setEnv] = useState({});
  const [saved, setSaved] = useState(false);
  const [cleared, setCleared] = useState("");

  useEffect(() => { fetchSettings().then(setData); fetchProviders().then((p) => setProviders(p?.providers || [])); }, []);

  const cur = (path, d) => {
    const pending = path.split(".").reduce((x, k) => (x == null ? x : x[k]), cfg);
    return pending !== undefined ? pending : get(data?.config, path, d);
  };
  const setC = (path, value) => setCfg((c) => deepMerge({ ...c }, nest(path, value)));

  async function save() {
    await saveSettings(cfg, env);
    onModelsChanged?.();  // provider/key edits apply live — refresh the chat picker
    setSaved(true); setTimeout(() => setSaved(false), 2500);
  }
  async function wipe(scope) { await clearMemory(scope); setCleared(scope); onMemoryCleared?.(); setTimeout(() => setCleared(""), 2500); }

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           className="w-[820px] max-w-full h-[86vh] flex flex-col rounded-2xl bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line shadow-pop overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-line dark:border-night-line">
          <h2 className="font-serif text-lg">Settings</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink text-xl leading-none">×</button>
        </div>

        <div className="flex-1 flex min-h-0">
          {/* Left tab nav — grouped, icon + label (Hermes-style) */}
          <nav className="w-44 shrink-0 border-r border-line dark:border-night-line p-2 overflow-y-auto">
            {TAB_GROUPS.map((g) => (
              <div key={g.label} className="mb-2 last:mb-0">
                <div className="px-3 pt-1.5 pb-1 text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint dark:text-night-faint">{g.label}</div>
                <div className="space-y-0.5">
                  {g.tabs.map((t) => (
                    <button key={t} onClick={() => setTab(t)}
                            className={`w-full flex items-center gap-2.5 text-left px-3 py-2 rounded-lg text-[13.5px] transition ${tab === t ? "bg-brand-wash dark:bg-night-soft text-brand-deep dark:text-night-ink font-medium" : "text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft"}`}>
                      <TabIcon name={t} />
                      <span>{t}</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </nav>

          {/* Right content */}
          <div className="flex-1 overflow-y-auto p-5 text-sm">
            {!data ? <div className="text-ink-faint">Loading…</div> : (
              <>
                {tab === "Providers" && <ProvidersTab catalog={providers} onSaved={onModelsChanged} />}

                {tab === "Models" && <ModelsTab onSaved={onModelsChanged} />}

                {tab === "Behavior" && (
                  <Section title="Behavior">
                    <Field label="Default mode"><Select value={cur("conversation.default_mode", "agent")} onChange={(v) => setC("conversation.default_mode", v)} options={["agent", "chat"]} /></Field>
                    <Toggle label="Auto mode — run tools (incl. shell) without asking" checked={!!cur("conversation.auto_approve", false)} onChange={(v) => setC("conversation.auto_approve", v)} />
                    <Field label="Tool step limit (0 = unlimited)"><Input type="number" value={cur("conversation.tool_loop_limit", 0)} onChange={(v) => setC("conversation.tool_loop_limit", parseInt(v || "0", 10))} /></Field>
                    <Field label="Memory nudge every N turns (0 = off)"><Input type="number" value={cur("conversation.memory_nudge_every", 6)} onChange={(v) => setC("conversation.memory_nudge_every", parseInt(v || "0", 10))} /></Field>
                    <Field label="History turns kept"><Input type="number" value={cur("conversation.max_history_turns", 12)} onChange={(v) => setC("conversation.max_history_turns", parseInt(v || "0", 10))} /></Field>
                    <div className="pt-2 mt-1 border-t border-line dark:border-night-line" />
                    <div className="text-[12px] text-ink-faint dark:text-night-faint">Model tuning (applies to every model)</div>
                    <Field label="Max tokens"><Input type="number" value={cur("provider.max_tokens", 8192)} onChange={(v) => setC("provider.max_tokens", parseInt(v || "0", 10))} /></Field>
                    <Field label={`Temperature (${cur("provider.temperature", 0.3)})`}>
                      <input type="range" min="0" max="1" step="0.05" value={cur("provider.temperature", 0.3)}
                             onChange={(e) => setC("provider.temperature", parseFloat(e.target.value))} className="w-full" />
                    </Field>
                    <Field label="Timeout (s)"><Input type="number" value={cur("provider.timeout_s", 60)} onChange={(v) => setC("provider.timeout_s", parseInt(v || "0", 10))} /></Field>
                    <div className="pt-2 mt-1 border-t border-line dark:border-night-line" />
                    <div className="text-[12px] text-ink-faint dark:text-night-faint">Voice — server-side Piper TTS / local STT. (The per-message read-aloud button uses your browser's own TTS and is always available.)</div>
                    <Toggle label="Enable Piper voice" checked={!!cur("voice.enabled", true)} onChange={(v) => setC("voice.enabled", v)} />
                  </Section>
                )}

                {tab === "Persona" && <PersonaTab onAssistantNameChanged={onAssistantNameChanged} />}

                {tab === "Browser" && (
                  <Section title="Browser & media">
                    <Field label="Preferred browser"><Select value={cur("browser.preferred", "auto")} onChange={(v) => setC("browser.preferred", v)} options={["auto", "chrome", "chromium", "brave", "edge", "vivaldi", "opera", "firefox"]} /></Field>
                    <Toggle label="Reuse my real browser profile (sign-ins)" checked={!!cur("browser.use_system_profile", true)} onChange={(v) => setC("browser.use_system_profile", v)} />
                    <Toggle label="Open videos fullscreen" checked={!!cur("browser.fullscreen", true)} onChange={(v) => setC("browser.fullscreen", v)} />
                    <Toggle label="Headless (no visible window)" checked={!!cur("browser.headless", false)} onChange={(v) => setC("browser.headless", v)} />
                  </Section>
                )}

                {tab === "Notifications" && <NotificationsTab />}

                {tab === "Messaging" && (
                  <>
                    <GatewayControl />
                    <Section title="Telegram" hint="Chat with Namma Agent from your phone (outbound + inbound). Stored in .env.">
                      <Field label="Bot token"><Input type="password" placeholder={data.env_set?.NAMMA_TELEGRAM_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_TELEGRAM_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_TELEGRAM_TOKEN: v }))} /></Field>
                      <Field label="Chat id"><Input placeholder={data.env_set?.NAMMA_TELEGRAM_CHAT_ID ? "(set)" : "not set"} value={env.NAMMA_TELEGRAM_CHAT_ID ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_TELEGRAM_CHAT_ID: v }))} /></Field>
                      <Toggle label="Reply to inbound Telegram messages" checked={!!cur("comms.inbound_enabled", true)} onChange={(v) => setC("comms.inbound_enabled", v)} />
                    </Section>
                    <Section title="Discord" hint="Webhook = send-only. To receive & reply, add a bot token (the bot dials out to Discord — works locally, no public URL). Enable the Message Content Intent in the Developer Portal.">
                      <Field label="Webhook URL (outbound)"><Input type="password" placeholder={data.env_set?.NAMMA_DISCORD_WEBHOOK_URL ? "•••••• (set)" : "not set"} value={env.NAMMA_DISCORD_WEBHOOK_URL ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_DISCORD_WEBHOOK_URL: v }))} /></Field>
                      <Field label="Bot token (two-way)"><Input type="password" placeholder={data.env_set?.NAMMA_DISCORD_BOT_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_DISCORD_BOT_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_DISCORD_BOT_TOKEN: v }))} /></Field>
                      <Field label="Channel id (optional)"><Input placeholder={data.env_set?.NAMMA_DISCORD_CHANNEL_ID ? "(set)" : "restrict to one channel"} value={env.NAMMA_DISCORD_CHANNEL_ID ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_DISCORD_CHANNEL_ID: v }))} /></Field>
                    </Section>
                    <Section title="Slack" hint="Webhook needs a public URL to receive. For local two-way use Socket Mode: add an app-level (xapp-) token + a bot (xoxb-) token and subscribe to message events — no public URL needed.">
                      <Field label="Webhook URL (outbound)"><Input type="password" placeholder={data.env_set?.NAMMA_SLACK_WEBHOOK_URL ? "•••••• (set)" : "not set"} value={env.NAMMA_SLACK_WEBHOOK_URL ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SLACK_WEBHOOK_URL: v }))} /></Field>
                      <Field label="App token (xapp-, Socket Mode)"><Input type="password" placeholder={data.env_set?.NAMMA_SLACK_APP_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_SLACK_APP_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SLACK_APP_TOKEN: v }))} /></Field>
                      <Field label="Bot token (xoxb-, replies)"><Input type="password" placeholder={data.env_set?.NAMMA_SLACK_BOT_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_SLACK_BOT_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SLACK_BOT_TOKEN: v }))} /></Field>
                    </Section>
                    <Section title="WhatsApp" hint="Outbound via the WhatsApp Cloud API (Meta).">
                      <Field label="Access token"><Input type="password" placeholder={data.env_set?.NAMMA_WHATSAPP_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_WHATSAPP_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_WHATSAPP_TOKEN: v }))} /></Field>
                      <Field label="Phone number id"><Input placeholder={data.env_set?.NAMMA_WHATSAPP_PHONE_ID ? "(set)" : "not set"} value={env.NAMMA_WHATSAPP_PHONE_ID ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_WHATSAPP_PHONE_ID: v }))} /></Field>
                      <Field label="Recipient (E.164)"><Input placeholder={data.env_set?.NAMMA_WHATSAPP_TO ? "(set)" : "e.g. 919876543210"} value={env.NAMMA_WHATSAPP_TO ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_WHATSAPP_TO: v }))} /></Field>
                    </Section>
                    <Section title="Signal" hint="Outbound via a signal-cli REST API service.">
                      <Field label="API URL"><Input placeholder={data.env_set?.NAMMA_SIGNAL_API_URL ? "(set)" : "http://localhost:8080"} value={env.NAMMA_SIGNAL_API_URL ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SIGNAL_API_URL: v }))} /></Field>
                      <Field label="Sender number (E.164)"><Input placeholder={data.env_set?.NAMMA_SIGNAL_NUMBER ? "(set)" : "+919876543210"} value={env.NAMMA_SIGNAL_NUMBER ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SIGNAL_NUMBER: v }))} /></Field>
                      <Field label="Recipient / group id"><Input placeholder={data.env_set?.NAMMA_SIGNAL_RECIPIENT ? "(set)" : "not set"} value={env.NAMMA_SIGNAL_RECIPIENT ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SIGNAL_RECIPIENT: v }))} /></Field>
                    </Section>
                  </>
                )}

                {tab === "Skills" && <SkillsTab />}

                {tab === "Toolsets" && <ToolsetsTab />}

                {tab === "Packs" && <PacksTab />}

                {tab === "Appearance" && (
                  <>
                    <Section title="Theme" hint="Pick a palette — applies instantly across the whole app.">
                      <ThemePicker themeName={themeName} onThemeNameChange={onThemeNameChange} />
                    </Section>
                    <Section title="Appearance & system">
                      <Toggle label="Dark theme" checked={theme === "dark"} onChange={onThemeToggle} />
                      <Field label="Log level"><Select value={cur("logging.level", "info")} onChange={(v) => setC("logging.level", v)} options={["debug", "info", "warning", "error"]} /></Field>
                    </Section>
                  </>
                )}

                {tab === "Memory" && (
                  <Section title="Memory" hint="Erase stored memory. This cannot be undone.">
                    <div className="flex flex-wrap gap-2">
                      {["facts", "conversations", "notes", "all"].map((s) => (
                        <button key={s} onClick={() => wipe(s)}
                                className="px-3 py-1.5 rounded-lg border border-line dark:border-night-line hover:bg-brand-wash dark:hover:bg-night-soft capitalize">Clear {s}</button>
                      ))}
                    </div>
                    {cleared && <div className="mt-2 text-brand-deep text-[13px]">Cleared {cleared}.</div>}
                  </Section>
                )}

                {tab === "About" && <AboutTab />}
              </>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-line dark:border-night-line">
          {saved && <span className="text-brand-deep text-[13px] mr-auto">Saved — applied live.</span>}
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-ink-soft dark:text-night-ink hover:bg-paper-soft dark:hover:bg-night-soft">Close</button>
          <button onClick={save} className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep">Save</button>
        </div>
      </div>
    </div>
  );
}

// The gateway control shown at the top of the Messaging tab: one standalone
// inbound service that handles every configured channel. Start it to begin
// receiving/replying to messages (Telegram + Signal poll locally; Slack +
// WhatsApp need the server publicly reachable); stop it to go silent. Outbound
// notifications work regardless.
function GatewayControl() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const refresh = () => fetchCommsStatus().then((s) => s && setStatus(s));
  useEffect(() => { refresh(); }, []);

  async function act(fn) {
    setBusy(true); setNote("");
    const s = await fn();
    if (s) { setStatus(s); if (s.error) setNote(s.error); }
    setBusy(false);
  }

  if (status && status.configured === false) {
    return (
      <Section title="Gateway" hint="The standalone service that handles all inbound messaging.">
        <div className="text-[13px] text-ink-faint dark:text-night-faint">Messaging is unavailable in this build.</div>
      </Section>
    );
  }

  const running = !!status?.running;
  const available = status?.available || [];
  const polling = status?.polling || [];
  const webhooks = status?.webhooks || [];

  return (
    <Section title="Gateway"
             hint="One service handles all inbound messaging across every configured channel. Start it to chat with your assistant from your messengers; stop it to go silent. (Outbound notifications always work.)">
      <div className="rounded-xl border border-line dark:border-night-line p-3 space-y-2.5">
        <div className="flex items-center gap-2.5">
          <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${running ? "bg-emerald-500" : "bg-line dark:bg-night-line"}`} />
          <span className="text-[13.5px] font-medium text-ink dark:text-night-ink">
            {status === null ? "Checking…" : running ? "Running" : "Stopped"}
          </span>
          <div className="ml-auto flex gap-2">
            <button onClick={() => act(startComms)} disabled={busy || running}
                    className="px-3 py-1.5 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-40 text-[13px]">
              {busy && !running ? "Starting…" : "Start"}
            </button>
            <button onClick={() => act(stopComms)} disabled={busy || !running}
                    className="px-3 py-1.5 rounded-lg border border-line dark:border-night-line hover:bg-paper-soft dark:hover:bg-night-soft disabled:opacity-40 text-[13px]">
              {busy && running ? "Stopping…" : "Stop"}
            </button>
          </div>
        </div>
        <div className="text-[12px] text-ink-faint dark:text-night-faint">
          {available.length
            ? <>Configured channels: <span className="text-ink-soft dark:text-night-ink">{available.join(", ")}</span></>
            : "No channels configured yet — add a token below, save, then Start."}
          {running && polling.length > 0 && <div>Polling: {polling.join(", ")}</div>}
          {running && webhooks.length > 0 && <div>Webhooks: {webhooks.join(", ")}</div>}
        </div>
        {note && <div className="text-[12px] text-brand-deep dark:text-amber-400">{note}</div>}
      </div>
      <div className="text-[11.5px] text-ink-faint dark:text-night-faint">
        Tip: after adding or changing a token, click <b>Save</b> below, then <b>Start</b> (or Stop &amp; Start) so the gateway picks it up.
      </div>
    </Section>
  );
}

// A titled settings block with generous vertical rhythm.
const Block = ({ title, hint, children }) => (
  <section className="space-y-3">
    <div>
      <h3 className="text-[15px] font-medium text-ink dark:text-night-ink">{title}</h3>
      {hint && <p className="mt-0.5 text-[12px] leading-relaxed text-ink-faint dark:text-night-faint">{hint}</p>}
    </div>
    {children}
  </section>
);
// A card holding a list of toggle rows, each row comfortably padded and divided.
const ToggleCard = ({ rows, disabled }) => (
  <div className={"rounded-xl border border-line dark:border-night-line divide-y divide-line dark:divide-night-line overflow-hidden " +
    (disabled ? "opacity-50 pointer-events-none" : "")}>
    {rows.map((r) => (
      <div key={r.id} className="px-3.5 py-3"><Toggle label={r.label} checked={r.checked} onChange={r.onChange} /></div>
    ))}
  </div>
);

// The "Notifications" tab — Phases 5 + 6. Two halves, both client-only
// (localStorage, like the theme — no Save round-trip):
//   • Desktop notifications — native OS toasts delivered by the backend (reliable
//     inside the pywebview window): master switch, per-event toggles, a test button.
//   • Sounds — synthesised interaction cues: master switch, volume, the completion
//     -sound preset picker (click to set & hear, ▶ to preview), per-event toggles.
function NotificationsTab() {
  // ── Desktop notifications ──
  const [notif, setNotif] = useState(notifyEnabled());
  const [notifEvents, setNotifEvents] = useState(
    () => Object.fromEntries(NOTIFY_EVENTS.map((e) => [e.id, notifyEventEnabled(e.id)])));
  const [testMsg, setTestMsg] = useState("");

  const flipNotif = (v) => { setNotif(v); setNotifyEnabled(v); };
  const flipNotifEvent = (id, v) => { setNotifEvents((e) => ({ ...e, [id]: v })); setNotifyEventEnabled(id, v); };
  const test = async () => {
    const ok = await sendTestNotification();
    setTestMsg(ok ? "Sent — check your desktop." : "Couldn't show a notification on this device.");
    setTimeout(() => setTestMsg(""), 5000);
  };

  // ── Sounds ──
  const [on, setOn] = useState(soundsEnabled());
  const [vol, setVol] = useState(soundVolume());
  const [preset, setPreset] = useState(completionPreset());
  const [sndEvents, setSndEvents] = useState(
    () => Object.fromEntries(SOUND_EVENTS.map((e) => [e.id, soundEventEnabled(e.id)])));

  const flipOn = (v) => { setOn(v); setSoundsEnabled(v); };
  const changeVol = (v) => { setVol(v); setSoundVolume(v); };
  const choosePreset = (id) => { setPreset(id); setCompletionPreset(id); previewPreset(id); };
  const flipSndEvent = (id, v) => { setSndEvents((e) => ({ ...e, [id]: v })); setSoundEventEnabled(id, v); };

  return (
    <div className="space-y-8">
      {/* ── Desktop notifications ── */}
      <Block title="Desktop notifications"
             hint="Native pop-ups from your OS when a reply is ready or your assistant needs you — they reach you even when the window is in the background.">
        <ToggleCard rows={[{ id: "master", label: "Enable notifications", checked: notif, onChange: flipNotif }]} />
        <div className="space-y-2">
          <div className="text-[12px] font-medium text-ink-soft dark:text-night-faint">Notify me about</div>
          <ToggleCard disabled={!notif}
                      rows={NOTIFY_EVENTS.map((e) => ({ id: e.id, label: e.label, checked: notifEvents[e.id], onChange: (v) => flipNotifEvent(e.id, v) }))} />
        </div>
        <div className="flex items-center gap-3 pt-0.5">
          <button onClick={test} className={_btnGhost}>Send test notification</button>
          {testMsg && <span className="text-[12px] text-ink-faint dark:text-night-faint">{testMsg}</span>}
        </div>
      </Block>

      <div className="border-t border-line dark:border-night-line" />

      {/* ── Sounds ── */}
      <Block title="Interaction sounds"
             hint="Short, synthesised cues on the moments of a turn — sent, each action step, and the reply landing. They play in your browser; nothing is sent anywhere.">
        <ToggleCard rows={[{ id: "snd", label: "Enable sounds", checked: on, onChange: flipOn }]} />
        <div className={"flex items-center gap-3 " + (on ? "" : "opacity-50 pointer-events-none")}>
          <span className="text-[13px] text-ink-soft dark:text-night-faint w-20 shrink-0">Volume</span>
          <input type="range" min="0" max="1" step="0.05" value={vol}
                 onChange={(e) => changeVol(parseFloat(e.target.value))} disabled={!on} className="flex-1" />
          <span className="text-[12px] tabular-nums text-ink-faint dark:text-night-faint w-9 text-right">{Math.round(vol * 100)}%</span>
        </div>
      </Block>

      <Block title="Completion sound" hint="The sound when a reply is ready. Click a preset to set it and hear it; ▶ previews without changing your pick.">
        <div className={`grid grid-cols-2 gap-2.5 ${on ? "" : "opacity-50 pointer-events-none"}`}>
          {COMPLETION_PRESETS.map((p) => {
            const active = preset === p.id;
            return (
              <button key={p.id} type="button" onClick={() => choosePreset(p.id)}
                      className={"flex items-center justify-between gap-2 rounded-xl border px-3.5 py-2.5 text-left text-[13px] transition " +
                        (active ? "border-brand ring-2 ring-brand/30 bg-brand-wash dark:bg-night-soft" : "border-line dark:border-night-line hover:border-brand/50")}>
                <span className="truncate text-ink dark:text-night-ink">{p.label}</span>
                <span role="button" tabIndex={-1} className="shrink-0 grid place-items-center h-6 w-6 rounded-full text-ink-faint dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-line" title="Preview"
                      onClick={(e) => { e.stopPropagation(); previewPreset(p.id); }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                </span>
              </button>
            );
          })}
        </div>
      </Block>

      <Block title="Play a sound for" hint="Turn individual cues off without muting everything.">
        <ToggleCard disabled={!on}
                    rows={SOUND_EVENTS.map((e) => ({ id: e.id, label: e.label, checked: sndEvents[e.id], onChange: (v) => flipSndEvent(e.id, v) }))} />
      </Block>
    </div>
  );
}

// The "Persona" tab: rename the assistant, pick a personality from a dropdown
// (each shown with a one-line identity), and create new personas — either by
// describing one and letting the assistant draft it, or by writing the
// instructions yourself. User personas live in ~/.namma_agent/personas and can be
// deleted; the built-ins that ship with Namma Agent can't.
const _pinput = "w-full rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 text-[13px] outline-none focus:border-brand";

function PersonaTab({ onAssistantNameChanged }) {
  const [list, setList] = useState(null);
  const [active, setActive] = useState("");
  const [name, setName] = useState("");
  const [nameSaved, setNameSaved] = useState(false);
  const [showManual, setShowManual] = useState(false);
  const blankDraft = { id: "", name: "", identity: "", tone: "", dos: "", donts: "" };
  const [draft, setDraft] = useState(blankDraft);
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetchPersonas().then((r) => {
      if (!r) return;
      setList(r.personas || []); setActive(r.active || "");
      if (r.assistant_name) setName(r.assistant_name);
    });
  }, []);

  async function choosePersona(id) {
    setActive(id);
    await setPersona(id);
  }
  async function saveName() {
    const n = name.trim(); if (!n) return;
    await saveSettings({ assistant: { name: n } }, {});
    onAssistantNameChanged?.(n);
    setNameSaved(true); setTimeout(() => setNameSaved(false), 2000);
  }
  async function generate() {
    setBusy(true); setMsg("");
    const r = await generatePersona(desc);
    setBusy(false);
    if (r?.ok && r.persona) {
      const p = r.persona;
      setDraft({ id: "", name: p.name || "", identity: p.identity || "", tone: p.tone || "",
                 dos: (p.dos || []).join("\n"), donts: (p.donts || []).join("\n") });
      setShowManual(true); setMsg("Drafted below — review, tweak, then Save persona.");
    } else setMsg(r?.error || "couldn't generate a persona");
  }
  async function editPersona(id) {
    setMsg("");
    const r = await fetchPersona(id);
    if (r?.ok && r.persona) {
      const p = r.persona;
      // Keep the id so saving edits this persona in place (editing a built-in
      // writes an editable copy that overrides it).
      setDraft({ id: p.id, name: p.name || "", identity: p.identity || "", tone: p.tone || "",
                 dos: (p.dos || []).join("\n"), donts: (p.donts || []).join("\n") });
      setShowManual(true);
      if (p.source === "builtin") setMsg("Editing a built-in saves your own editable copy that overrides it.");
    } else setMsg("couldn't load that persona");
  }
  function newDraft() { setDraft(blankDraft); setShowManual(true); setMsg(""); }
  async function saveDraft() {
    setBusy(true); setMsg("");
    const r = await savePersona(draft);
    setBusy(false);
    if (r?.ok) {
      setList(r.personas || list);
      setDraft(blankDraft); setDesc(""); setShowManual(false); setMsg("");
      if (r.saved?.id) choosePersona(r.saved.id);
    } else setMsg(r?.error || "couldn't save the persona");
  }
  async function remove(id) {
    const r = await deletePersona(id);
    if (r) { setList(r.personas || []); setActive(r.active || active); }
  }

  if (list === null) return <div className="text-ink-faint">Loading…</div>;
  return (
    <div className="space-y-5">
      <Section title="Assistant name" hint="What your assistant is called everywhere — chat, voice, Telegram, the window title.">
        <div className="flex gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") saveName(); }}
                 placeholder="e.g. Heaven, Jarvis, Aria" className={_pinput} />
          <button onClick={saveName} className={_btn}>Save name</button>
        </div>
        {nameSaved && <div className="text-brand-deep dark:text-emerald-400 text-[13px]">Saved — applied live.</div>}
      </Section>

      <div className="border-t border-line dark:border-night-line" />

      <Section title="Persona" hint="The personality your assistant uses. Switching applies immediately.">
        <select value={active} onChange={(e) => choosePersona(e.target.value)}
                className="w-full rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-2 py-1.5 text-[13px] outline-none focus:border-brand">
          {list.map((p) => <option key={p.id} value={p.id}>{p.name}{p.identity_line ? ` — ${p.identity_line}` : ""}</option>)}
        </select>
        <div className="space-y-1.5 mt-1">
          {list.map((p) => (
            <div key={p.id} className="flex items-center gap-2 text-[13px]">
              <span className={`h-2 w-2 rounded-full shrink-0 ${p.id === active ? "bg-brand" : "bg-line dark:bg-night-line"}`} />
              <span className="font-medium shrink-0">{p.name}</span>
              <span className="text-ink-faint dark:text-night-faint truncate flex-1">{p.identity_line}</span>
              <button onClick={() => editPersona(p.id)} title="Edit / view full instructions"
                      className="text-[12px] underline text-ink-faint dark:text-night-faint hover:text-ink dark:hover:text-night-ink shrink-0">
                {p.source === "user" ? "edit" : "view"}
              </button>
              {p.source === "user"
                ? <button onClick={() => remove(p.id)} title="Delete persona" className="px-1 text-ink-faint hover:text-red-500 text-base leading-none shrink-0">×</button>
                : <span className="text-[11px] text-ink-faint dark:text-night-faint shrink-0">built-in</span>}
            </div>
          ))}
        </div>
      </Section>

      <div className="border-t border-line dark:border-night-line" />

      <Section title="Create a persona" hint="Describe one and let your assistant draft it, or write the instructions yourself.">
        <div className="flex gap-2">
          <input value={desc} onChange={(e) => setDesc(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter" && desc.trim()) generate(); }}
                 placeholder="Describe it, e.g. “a calm stoic mentor who teaches by asking questions”"
                 className={_pinput} />
          <button onClick={generate} disabled={busy || !desc.trim()} className={_btn}>
            {busy ? "…" : "Generate"}
          </button>
        </div>
        <button type="button" onClick={() => (showManual ? setShowManual(false) : newDraft())}
                className="text-[12.5px] underline text-ink-faint dark:text-night-faint">
          {showManual ? "hide editor" : "or write it manually"}
        </button>

        {showManual && (
          <div className="space-y-2 rounded-xl border border-line dark:border-night-line p-3">
            <div className="text-[12px] text-ink-faint dark:text-night-faint">
              {draft.id ? `Editing “${draft.id}”` : "New persona"}
            </div>
            <input value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                   placeholder="Persona name (e.g. “Sage”)" className={_pinput} />
            <textarea value={draft.identity} onChange={(e) => setDraft((d) => ({ ...d, identity: e.target.value }))}
                      rows={4} placeholder="Identity — the “You are …” system-prompt text. Use {name} where the assistant's name should appear."
                      className={`${_pinput} resize-y`} />
            <input value={draft.tone} onChange={(e) => setDraft((d) => ({ ...d, tone: e.target.value }))}
                   placeholder="Tone (comma-separated, e.g. warm, witty, capable)" className={_pinput} />
            <div className="flex gap-2">
              <textarea value={draft.dos} onChange={(e) => setDraft((d) => ({ ...d, dos: e.target.value }))}
                        rows={3} placeholder="Do — one rule per line" className={`${_pinput} resize-y`} />
              <textarea value={draft.donts} onChange={(e) => setDraft((d) => ({ ...d, donts: e.target.value }))}
                        rows={3} placeholder="Don't — one rule per line" className={`${_pinput} resize-y`} />
            </div>
            <button onClick={saveDraft} disabled={busy || !draft.name.trim() || !draft.identity.trim()} className={_btn}>
              {busy ? "Saving…" : "Save persona"}
            </button>
          </div>
        )}
        {msg && <div className="text-[13px] text-brand-deep dark:text-emerald-400">{msg}</div>}
      </Section>
    </div>
  );
}

// The "Providers" tab: a list of named provider connections. You configure each
// one ONCE — type, base_url, and its OWN .env key variable + value — so Opencode,
// Groq, OpenAI, … coexist with independent keys. Models (next tab) just pick one.
function ProvidersTab({ catalog, onSaved }) {
  const [list, setList] = useState(null);
  const [keys, setKeys] = useState({});      // api_key_env -> typed value
  const [envSet, setEnvSet] = useState({});  // api_key_env -> already set in .env?
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const refreshEnv = (rows) => {
    const names = [...new Set((rows || []).map((p) => (p.api_key_env || "").trim()).filter(Boolean))];
    if (names.length) fetchEnvStatus(names).then((r) => setEnvSet((s) => ({ ...s, ...(r?.env_set || {}) })));
  };
  useEffect(() => { fetchConfiguredProviders().then((r) => { setList(r?.providers || []); refreshEnv(r?.providers || []); }); }, []);

  const update = (i, patch) => setList((l) => l.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  const remove = (i) => setList((l) => l.filter((_, j) => j !== i));
  const add = () => {
    const def = catalog.find((p) => p.type === "opencode") || catalog[0] || {};
    setList((l) => [...(l || []), { label: "", type: def.type || "openai_compat",
      base_url: def.base_url || "", api_key_env: def.key_env || "" }]);
  };
  async function save() {
    setSaving(true);
    const clean = (list || []).filter((p) => (p.type || "").trim());
    const envToWrite = {};
    for (const [name, val] of Object.entries(keys)) if (name && val) envToWrite[name] = val;
    if (Object.keys(envToWrite).length) await saveSettings({}, envToWrite);
    const r = await saveConfiguredProviders(clean);
    setList(r?.providers || clean); setKeys({}); refreshEnv(r?.providers || clean);
    onSaved?.();
    setSaving(false); setSaved(true); setTimeout(() => setSaved(false), 2500);
  }

  if (list === null) return <div className="text-ink-faint">Loading…</div>;
  return (
    <Section title="Providers"
             hint="Add each provider once — with its OWN API key. Opencode, Groq, OpenAI, a local server… they no longer share one key. Then pick models from them in the Models tab.">
      <div className="space-y-3">
        {list.length === 0 && (
          <div className="text-[13px] text-ink-faint dark:text-night-faint">No providers yet — add one (e.g. Opencode, then Groq) and give each its own key.</div>
        )}
        {list.map((row, i) => (
          <ProviderConnRow key={i} row={row} catalog={catalog}
                           keyValue={keys[row.api_key_env] ?? ""} keySet={!!envSet[row.api_key_env]}
                           onKey={(v) => row.api_key_env && setKeys((k) => ({ ...k, [row.api_key_env]: v }))}
                           onChange={(patch) => update(i, patch)} onRemove={() => remove(i)} />
        ))}
        <button onClick={add}
                className="w-full py-2 rounded-lg border border-dashed border-line dark:border-night-line text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft text-[13px]">
          + Add a provider
        </button>
        <div className="flex items-center gap-3 pt-1">
          <button onClick={save} disabled={saving}
                  className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50">
            {saving ? "Saving…" : "Save providers"}
          </button>
          {saved && <span className="text-brand-deep text-[13px]">Saved — now add models from these in the Models tab.</span>}
        </div>
      </div>
    </Section>
  );
}

function ProviderConnRow({ row, catalog, onChange, onRemove, keyValue = "", keySet = false, onKey }) {
  const [test, setTest] = useState(null); // {ok, count, error} after a connection test
  const [testing, setTesting] = useState(false);

  function pickType(type) {
    const c = catalog.find((x) => x.type === type) || {};
    // Default the base_url + suggest a key variable for the newly chosen type.
    onChange({ type, base_url: c.base_url || "", api_key_env: suggestKeyEnv(type, row.label, catalog) });
  }
  async function testConn() {
    setTesting(true); setTest(null);
    const r = await fetchModels(row.type, row.base_url || "", keyValue || "");
    setTest({ ok: r?.source === "live", count: (r?.models || []).length, error: r?.error || "" });
    setTesting(false);
  }
  const needsBase = catalog.find((p) => p.type === row.type)?.needs_base_url;

  return (
    <div className="rounded-xl border border-line dark:border-night-line p-3 space-y-2">
      <div className="flex items-center gap-2">
        <input value={row.label || ""}
               onChange={(e) => {
                 const label = e.target.value;
                 const patch = { label };
                 // Keep the key var in sync with the name until the user edits it
                 // by hand (so “Groq” → GROQ_API_KEY automatically).
                 const typeDefault = suggestKeyEnv(row.type, "", catalog);
                 if (!row.api_key_env || row.api_key_env === typeDefault)
                   patch.api_key_env = suggestKeyEnv(row.type, label, catalog);
                 onChange(patch);
               }}
               placeholder="Name (e.g. “Groq”, “Opencode”)"
               className="flex-1 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 text-[13px] outline-none focus:border-brand" />
        <select value={row.type || ""} onChange={(e) => pickType(e.target.value)}
                className="w-44 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-2 py-1.5 text-[13px] outline-none focus:border-brand">
          {catalog.map((p) => <option key={p.type} value={p.type}>{p.label}</option>)}
        </select>
        <button onClick={onRemove} title="Remove" className="px-2 text-ink-faint hover:text-red-500 text-lg leading-none">×</button>
      </div>
      {(needsBase || row.base_url) && (
        <input value={row.base_url || ""} onChange={(e) => onChange({ base_url: e.target.value })}
               placeholder="Base URL, e.g. https://api.groq.com/openai/v1"
               className="w-full rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 text-[13px] outline-none focus:border-brand" />
      )}
      <div className="flex gap-2">
        <input value={row.api_key_env || ""} onChange={(e) => onChange({ api_key_env: e.target.value })}
               placeholder="API key variable" title="The .env variable that holds THIS provider's key — keep it distinct per provider (OPENAI_API_KEY, GROQ_API_KEY, …)"
               className="w-52 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 text-[13px] font-mono outline-none focus:border-brand" />
        <input type="password" value={keyValue} onChange={(e) => onKey?.(e.target.value)}
               placeholder={keySet ? "•••••• (set) — type to replace" : "paste this provider's API key"}
               className="flex-1 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 text-[13px] outline-none focus:border-brand" />
        <button onClick={testConn} disabled={testing} title="Test connection — list this provider's models"
                className="px-3 rounded-lg border border-line dark:border-night-line hover:bg-paper-soft dark:hover:bg-night-soft disabled:opacity-50 text-[13px]">
          {testing ? "…" : "Test"}
        </button>
      </div>
      <div className="text-[11.5px]">
        {test == null ? (
          <span className="text-ink-faint dark:text-night-faint">{keySet || keyValue ? "Key ready — Test to list models, then Save." : "Add the key, then Test."}</span>
        ) : test.ok ? (
          <span className="text-emerald-600 dark:text-emerald-400">● Connected — {test.count} models available.</span>
        ) : (
          <span className="text-brand-deep dark:text-amber-400">● {test.error || "Couldn't reach the provider — check the URL/key."}</span>
        )}
      </div>
    </div>
  );
}

// The "Models" tab: switchable model profiles. Each one just picks a configured
// provider + a model id from it — keys/URLs live on the provider, not here. These
// appear in the picker at the top of every chat (switching mid-chat = new session).
function ModelsTab({ onSaved }) {
  const [list, setList] = useState(null);
  const [provs, setProvs] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchConfiguredModels().then((r) => setList(r?.models || []));
    fetchConfiguredProviders().then((r) => setProvs(r?.providers || []));
  }, []);

  const update = (i, patch) => setList((l) => l.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  const remove = (i) => setList((l) => l.filter((_, j) => j !== i));
  const add = () => setList((l) => [...(l || []), { label: "", provider: provs[0]?.id || "", model: "" }]);
  async function save() {
    setSaving(true);
    const clean = (list || []).filter((m) => (m.model || "").trim());
    const r = await saveConfiguredModels(clean);
    setList(r?.models || clean);
    onSaved?.();
    setSaving(false); setSaved(true); setTimeout(() => setSaved(false), 2500);
  }

  if (list === null) return <div className="text-ink-faint">Loading…</div>;
  if (!provs.length) {
    return (
      <Section title="Your models" hint="Pick models from your providers to switch between in chat.">
        <div className="text-[13px] text-ink-faint dark:text-night-faint">
          Add a provider first — go to the <span className="font-medium text-ink-soft dark:text-night-ink">Providers</span> tab, add one (with its key), and Save. Then come back here to pick models from it.
        </div>
      </Section>
    );
  }
  return (
    <Section title="Your models"
             hint="Each model picks one of your providers + a model id from it. These are what you switch between at the top of every chat.">
      <div className="space-y-3">
        {list.length === 0 && (
          <div className="text-[13px] text-ink-faint dark:text-night-faint">No models yet — add one to switch between brains in chat.</div>
        )}
        {list.map((row, i) => (
          <ModelRow key={i} row={row} providers={provs}
                    onChange={(patch) => update(i, patch)} onRemove={() => remove(i)} />
        ))}
        <button onClick={add}
                className="w-full py-2 rounded-lg border border-dashed border-line dark:border-night-line text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft text-[13px]">
          + Add a model
        </button>
        <div className="flex items-center gap-3 pt-1">
          <button onClick={save} disabled={saving}
                  className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50">
            {saving ? "Saving…" : "Save models"}
          </button>
          {saved && <span className="text-brand-deep text-[13px]">Saved — available in every chat now.</span>}
        </div>
      </div>
    </Section>
  );
}

function ModelRow({ row, providers, onChange, onRemove }) {
  const [models, setModels] = useState([]);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // List the chosen provider's models (server reads its base_url + own key).
  async function load() {
    if (!row.provider) { setModels([]); return; }
    setLoading(true); setError("");
    const r = await fetchModelsForProvider(row.provider);
    setModels(r?.models || []); setSource(r?.source || ""); setError(r?.error || "");
    setLoading(false);
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [row.provider]);

  const dlId = `models-${row.provider}`;
  return (
    <div className="rounded-xl border border-line dark:border-night-line p-3 space-y-2">
      <div className="flex items-center gap-2">
        <input value={row.label || ""} onChange={(e) => onChange({ label: e.target.value })}
               placeholder="Display name (e.g. “Claude Opus”)"
               className="flex-1 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 text-[13px] outline-none focus:border-brand" />
        <button onClick={onRemove} title="Remove" className="px-2 text-ink-faint hover:text-red-500 text-lg leading-none">×</button>
      </div>
      <div className="flex gap-2">
        <select value={row.provider || ""} onChange={(e) => onChange({ provider: e.target.value })}
                className="w-44 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-2 py-1.5 text-[13px] outline-none focus:border-brand">
          {providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        <input list={dlId} value={row.model || ""} onChange={(e) => onChange({ model: e.target.value })}
               placeholder={loading ? "fetching models…" : "pick or type a model id"}
               className="flex-1 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 text-[13px] outline-none focus:border-brand" />
        <datalist id={dlId}>{models.map((m) => <option key={m} value={m} />)}</datalist>
        <button onClick={load} disabled={loading} title="Refresh model list"
                className="px-2.5 rounded-lg border border-line dark:border-night-line hover:bg-paper-soft dark:hover:bg-night-soft disabled:opacity-50">
          {loading ? "…" : "↻"}
        </button>
      </div>
      <div className="text-[11.5px]">
        {loading ? <span className="text-ink-faint dark:text-night-faint">Fetching…</span>
          : source === "live" ? <span className="text-emerald-600 dark:text-emerald-400">● {models.length} models available</span>
          : <span className="text-brand-deep dark:text-amber-400">● {error || "Set this provider's key in the Providers tab, then ↻."}</span>}
      </div>
    </div>
  );
}

const Section = ({ title, hint, children }) => (
  <div>
    <div className="font-medium mb-1">{title}</div>
    {hint && <div className="text-[12px] text-ink-faint dark:text-night-faint mb-3">{hint}</div>}
    <div className="space-y-2.5">{children}</div>
  </div>
);
const Field = ({ label, children }) => (
  <label className="flex items-center justify-between gap-3">
    <span className="text-ink-soft dark:text-night-faint">{label}</span>
    <div className="w-1/2">{children}</div>
  </label>
);
const Input = ({ value, onChange, ...p }) => (
  <input {...p} value={value} onChange={(e) => onChange(e.target.value)}
         className="w-full rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 outline-none focus:border-brand" />
);
const Select = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-2 py-1.5 outline-none focus:border-brand">
    {options.map((o) => <option key={o} value={o}>{o}</option>)}
  </select>
);
const Toggle = ({ label, checked, onChange }) => (
  <label className="flex items-center justify-between gap-3 cursor-pointer">
    <span className="text-ink-soft dark:text-night-faint">{label}</span>
    <button type="button" onClick={() => onChange(!checked)}
            className={`h-6 w-11 rounded-full transition relative shrink-0 ${checked ? "bg-brand" : "bg-line dark:bg-night-line"}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${checked ? "left-[22px]" : "left-0.5"}`} />
    </button>
  </label>
);

// The "Skills" tab: every skill (procedural playbook) with an on/off switch.
// Disabled skills drop out of the agent's catalog and use_skill refuses them.
// Skills that declare prerequisites (a CLI / env var) show what they need and are
// badged "needs setup" until those are present — they stay listed but the agent
// won't be told about them while the prerequisite is missing.
function SkillBadge({ children, tone = "muted" }) {
  const tones = {
    muted: "bg-paper-soft dark:bg-night-soft text-ink-faint dark:text-night-faint",
    warn: "bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-400",
  };
  return <span className={`px-1.5 py-0.5 rounded text-[11px] font-medium ${tones[tone]}`}>{children}</span>;
}

function SkillsTab() {
  const [skills, setSkills] = useState(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState({});   // name -> true while its toggle is in flight

  useEffect(() => { listSkills().then((r) => setSkills(r?.skills || [])); }, []);

  async function flip(s) {
    setBusy((b) => ({ ...b, [s.name]: true }));
    const next = !s.enabled;
    setSkills((list) => list.map((x) => x.name === s.name ? { ...x, enabled: next } : x));
    const r = await toggleSkill(s.name, next);
    if (!r?.ok) // revert on failure
      setSkills((list) => list.map((x) => x.name === s.name ? { ...x, enabled: s.enabled } : x));
    setBusy((b) => ({ ...b, [s.name]: false }));
  }

  if (!skills) return <div className="text-ink-faint dark:text-night-faint">Loading…</div>;

  const needle = q.trim().toLowerCase();
  const shown = skills.filter((s) =>
    !needle || s.name.toLowerCase().includes(needle) ||
    (s.description || "").toLowerCase().includes(needle) ||
    (s.category || "").toLowerCase().includes(needle));
  const byCat = {};
  for (const s of shown) (byCat[s.category || "general"] ||= []).push(s);
  const cats = Object.keys(byCat).sort();
  const enabledCount = skills.filter((s) => s.enabled).length;

  return (
    <div className="space-y-4">
      <Section title="Skills"
               hint={`Procedural playbooks the assistant can load mid-task. ${enabledCount} of ${skills.length} enabled. Turn one off to keep it out of the assistant's catalog.`}>
        <Input value={q} onChange={setQ} placeholder="Search skills…" />
      </Section>

      {cats.length === 0 && <div className="text-ink-faint dark:text-night-faint text-[13px]">No skills match “{q}”.</div>}

      {cats.map((cat) => (
        <div key={cat}>
          <div className="text-[12px] uppercase tracking-wide text-ink-faint dark:text-night-faint mb-2">
            {cat} <span className="opacity-60">({byCat[cat].length})</span>
          </div>
          <div className="space-y-1.5">
            {byCat[cat].map((s) => (
              <div key={s.name} className={`${_box} flex items-start justify-between gap-3`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium">{s.name}</span>
                    {s.source === "user" && <SkillBadge>yours</SkillBadge>}
                    {!s.supported && <SkillBadge tone="warn">needs setup</SkillBadge>}
                  </div>
                  {s.description && (
                    <div className="text-[12.5px] text-ink-faint dark:text-night-faint mt-0.5">{s.description}</div>
                  )}
                  {s.requires?.length > 0 && (
                    <div className="text-[11.5px] text-ink-faint dark:text-night-faint mt-1">
                      Requires: {s.requires.join(", ")}
                    </div>
                  )}
                </div>
                <button type="button" disabled={!!busy[s.name]} onClick={() => flip(s)}
                        className={`h-6 w-11 rounded-full transition relative shrink-0 mt-0.5 disabled:opacity-50 ${s.enabled ? "bg-brand" : "bg-line dark:bg-night-line"}`}>
                  <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${s.enabled ? "left-[22px]" : "left-0.5"}`} />
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// The "Toolsets" tab: every tool the assistant can call, grouped by toolset, with
// an on/off switch. Disabled tools drop out of what the model sees each turn and
// are refused if somehow called. A whole toolset can be flipped from its header.
// Destructive tools (approval-gated) are badged so it's clear what they can do.
function ToolsetsTab() {
  const [tools, setTools] = useState(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState({});   // name|cat -> true while a toggle is in flight

  useEffect(() => { listTools().then((r) => setTools(r?.tools || [])); }, []);

  async function flip(t) {
    setBusy((b) => ({ ...b, [t.name]: true }));
    const next = !t.enabled;
    setTools((list) => list.map((x) => x.name === t.name ? { ...x, enabled: next } : x));
    const r = await toggleTool(t.name, next);
    if (!r?.ok) // revert on failure
      setTools((list) => list.map((x) => x.name === t.name ? { ...x, enabled: t.enabled } : x));
    setBusy((b) => ({ ...b, [t.name]: false }));
  }

  async function flipCat(cat, items) {
    const key = `cat:${cat}`;
    const next = !items.every((t) => t.enabled);   // all on → turn off; else turn on
    setBusy((b) => ({ ...b, [key]: true }));
    const before = items.map((t) => ({ name: t.name, enabled: t.enabled }));
    setTools((list) => list.map((x) => x.category === cat ? { ...x, enabled: next } : x));
    const r = await toggleToolset(cat, next);
    if (!r?.ok) // revert on failure
      setTools((list) => list.map((x) => {
        const prev = before.find((b) => b.name === x.name);
        return prev ? { ...x, enabled: prev.enabled } : x;
      }));
    setBusy((b) => ({ ...b, [key]: false }));
  }

  if (!tools) return <div className="text-ink-faint dark:text-night-faint">Loading…</div>;

  const needle = q.trim().toLowerCase();
  const shown = tools.filter((t) =>
    !needle || t.name.toLowerCase().includes(needle) ||
    (t.description || "").toLowerCase().includes(needle) ||
    (t.category || "").toLowerCase().includes(needle));
  const byCat = {};
  for (const t of shown) (byCat[t.category || "general"] ||= []).push(t);
  const cats = Object.keys(byCat).sort();
  const enabledCount = tools.filter((t) => t.enabled).length;

  return (
    <div className="space-y-4">
      <Section title="Toolsets"
               hint={`Capabilities the assistant can call. ${enabledCount} of ${tools.length} enabled. Turn a tool — or a whole toolset — off to keep it out of every turn.`}>
        <Input value={q} onChange={setQ} placeholder="Search tools…" />
      </Section>

      {cats.length === 0 && <div className="text-ink-faint dark:text-night-faint text-[13px]">No tools match “{q}”.</div>}

      {cats.map((cat) => {
        const items = byCat[cat];
        const allOn = items.every((t) => t.enabled);
        return (
          <div key={cat}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-[12px] uppercase tracking-wide text-ink-faint dark:text-night-faint">
                {cat} <span className="opacity-60">({items.length})</span>
              </div>
              <button type="button" disabled={!!busy[`cat:${cat}`]} onClick={() => flipCat(cat, items)}
                      className="text-[11.5px] text-ink-faint dark:text-night-faint hover:text-brand disabled:opacity-50">
                {allOn ? "Disable all" : "Enable all"}
              </button>
            </div>
            <div className="space-y-1.5">
              {items.map((t) => (
                <div key={t.name} className={`${_box} flex items-start justify-between gap-3`}>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium font-mono text-[13px]">{t.name}</span>
                      {t.destructive && <SkillBadge tone="warn">needs approval</SkillBadge>}
                    </div>
                    {t.description && (
                      <div className="text-[12.5px] text-ink-faint dark:text-night-faint mt-0.5">{t.description}</div>
                    )}
                  </div>
                  <button type="button" disabled={!!busy[t.name]} onClick={() => flip(t)}
                          className={`h-6 w-11 rounded-full transition relative shrink-0 mt-0.5 disabled:opacity-50 ${t.enabled ? "bg-brand" : "bg-line dark:bg-night-line"}`}>
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${t.enabled ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// The "Packs" tab: export your own skills/tools as a shareable .zip, and import
// someone else's. Skills are markdown (safe, auto-install); tools are Python that
// runs in-process — so each tool is shown with its source and must be approved.
const _box = "rounded-xl border border-line dark:border-night-line p-3";
const _btn = "px-3 py-1.5 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50";
const _btnGhost = "px-3 py-1.5 rounded-lg border border-line dark:border-night-line hover:bg-paper-soft dark:hover:bg-night-soft";

function PacksTab() {
  const [items, setItems] = useState(null);                 // {skills:[], tools:[]}
  const [pick, setPick] = useState({ skills: {}, tools: {} }); // name/file -> bool
  const [busy, setBusy] = useState(false);
  const [exported, setExported] = useState(null);           // {filename, path}

  // import state
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);             // inspect result or {error}
  const [approve, setApprove] = useState({});               // tool name -> bool (default off)
  const [openSrc, setOpenSrc] = useState({});               // tool name -> expanded
  const [overwrite, setOverwrite] = useState(false);
  const [result, setResult] = useState(null);               // install summary

  useEffect(() => {
    fetchPackItems().then((r) => {
      const it = { skills: r?.skills || [], tools: r?.tools || [] };
      setItems(it);
      setPick({
        skills: Object.fromEntries(it.skills.map((s) => [s.name, true])),
        tools: Object.fromEntries(it.tools.map((t) => [t.file, true])),
      });
    });
  }, []);

  const toggle = (kind, key) => setPick((p) => ({ ...p, [kind]: { ...p[kind], [key]: !p[kind][key] } }));
  const selected = (kind) => Object.entries(pick[kind] || {}).filter(([, v]) => v).map(([k]) => k);

  async function doExport() {
    setBusy(true); setExported(null);
    const r = await exportPack(selected("skills"), selected("tools"));
    setBusy(false);
    if (r?.ok) setExported(r);
  }

  async function onPick(f) {
    setFile(f); setPreview(null); setResult(null); setApprove({}); setOpenSrc({});
    if (!f) return;
    setBusy(true);
    const r = await inspectPack(f);
    setBusy(false);
    setPreview(r || { error: "could not read file" });
  }

  async function doInstall() {
    setBusy(true); setResult(null);
    const approvedTools = (preview?.tools || []).filter((t) => approve[t.name]).map((t) => t.name);
    const skills = (preview?.skills || []).map((s) => s.name);
    const r = await installPack(file, { approvedTools, skills, overwrite });
    setBusy(false);
    setResult(r?.summary || (r?.error ? { error: r.error } : { error: "install failed" }));
    fetchPackItems().then((x) => setItems({ skills: x?.skills || [], tools: x?.tools || [] }));
  }

  if (!items) return <div className="text-ink-faint">Loading…</div>;
  const nSel = selected("skills").length + selected("tools").length;

  return (
    <div className="space-y-5">
      {/* ── Export ── */}
      <Section title="Export a pack"
               hint="Bundle your assistant-created skills and tools into one shareable .zip. Pick what to include; the file carries its own install instructions.">
        {items.skills.length === 0 && items.tools.length === 0 ? (
          <div className="text-ink-faint dark:text-night-faint text-[13px]">
            You haven't created any skills or tools yet. Ask the assistant to make one, then come back here to share it.
          </div>
        ) : (
          <>
            {items.skills.length > 0 && (
              <div className={_box}>
                <div className="text-[12px] text-ink-faint dark:text-night-faint mb-2">Skills</div>
                <div className="space-y-1.5">
                  {items.skills.map((s) => (
                    <label key={s.name} className="flex items-start gap-2 cursor-pointer">
                      <input type="checkbox" checked={!!pick.skills[s.name]} onChange={() => toggle("skills", s.name)} className="mt-1" />
                      <span><span className="font-medium">{s.name}</span>
                        {s.description && <span className="text-ink-faint dark:text-night-faint"> — {s.description}</span>}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            {items.tools.length > 0 && (
              <div className={_box}>
                <div className="text-[12px] text-ink-faint dark:text-night-faint mb-2">Tools <span className="opacity-70">(Python)</span></div>
                <div className="space-y-1.5">
                  {items.tools.map((t) => (
                    <label key={t.file} className="flex items-start gap-2 cursor-pointer">
                      <input type="checkbox" checked={!!pick.tools[t.file]} onChange={() => toggle("tools", t.file)} className="mt-1" />
                      <span><span className="font-medium">{t.name}</span>
                        {t.description && <span className="text-ink-faint dark:text-night-faint"> — {t.description}</span>}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="flex items-center gap-3">
              <button onClick={doExport} disabled={busy || nSel === 0} className={_btn}>
                {busy ? "Building…" : `Export ${nSel} item${nSel === 1 ? "" : "s"}`}
              </button>
              {exported && (
                <span className="text-[13px] text-brand-deep dark:text-emerald-400">
                  Saved. <a href={packDownloadUrl(exported.filename)} download className="underline">Download {exported.filename}</a>
                  <span className="block text-ink-faint dark:text-night-faint text-[11.5px]">{exported.path}</span>
                </span>
              )}
            </div>
          </>
        )}
      </Section>

      <div className="border-t border-line dark:border-night-line" />

      {/* ── Import ── */}
      <Section title="Import a pack"
               hint="Open a .zip someone shared with you. Skills install directly; tools run code on your machine, so review and approve each one.">
        <input type="file" accept=".zip,application/zip" onChange={(e) => onPick(e.target.files?.[0] || null)}
               className="block text-[13px] text-ink-soft dark:text-night-faint" />

        {preview?.error && <div className="text-red-500 text-[13px]">Couldn't read this pack: {preview.error}</div>}

        {preview && !preview.error && (
          <div className="space-y-3">
            {preview.created_by && (
              <div className="text-[12px] text-ink-faint dark:text-night-faint">
                From <span className="font-medium">{preview.created_by}</span>{preview.created ? ` · ${preview.created}` : ""}
              </div>
            )}

            {preview.skills?.length > 0 && (
              <div className={_box}>
                <div className="text-[12px] text-ink-faint dark:text-night-faint mb-2">Skills (install directly)</div>
                <div className="space-y-1">
                  {preview.skills.map((s) => (
                    <div key={s.name} className="text-[13px]">
                      <span className="font-medium">{s.name}</span>
                      {s.description && <span className="text-ink-faint dark:text-night-faint"> — {s.description}</span>}
                      {s.exists && <span className="ml-2 text-amber-600 dark:text-amber-400 text-[11.5px]">already installed</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {preview.tools?.length > 0 && (
              <div className={_box}>
                <div className="text-[12px] text-amber-600 dark:text-amber-400 mb-2">
                  ⚠️ Tools run Python in-process. Only approve tools from a source you trust — review the source first.
                </div>
                <div className="space-y-2">
                  {preview.tools.map((t) => (
                    <div key={t.name} className="rounded-lg border border-line dark:border-night-line p-2">
                      <label className="flex items-start gap-2 cursor-pointer">
                        <input type="checkbox" checked={!!approve[t.name]}
                               onChange={() => setApprove((a) => ({ ...a, [t.name]: !a[t.name] }))} className="mt-1" />
                        <span className="flex-1">
                          <span className="font-medium">{t.name}</span>
                          {t.description && <span className="text-ink-faint dark:text-night-faint"> — {t.description}</span>}
                          {t.exists && <span className="ml-2 text-amber-600 dark:text-amber-400 text-[11.5px]">already installed</span>}
                        </span>
                        <button type="button" onClick={(e) => { e.preventDefault(); setOpenSrc((o) => ({ ...o, [t.name]: !o[t.name] })); }}
                                className="text-[12px] underline text-ink-faint dark:text-night-faint shrink-0">
                          {openSrc[t.name] ? "hide source" : "view source"}
                        </button>
                      </label>
                      {openSrc[t.name] && (
                        <pre className="mt-2 max-h-64 overflow-auto rounded bg-paper-soft dark:bg-night text-[11.5px] p-2 whitespace-pre-wrap">{t.source || "(source unavailable)"}</pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {(preview.skills?.some((s) => s.exists) || preview.tools?.some((t) => t.exists)) && (
              <Toggle label="Overwrite items that already exist" checked={overwrite} onChange={setOverwrite} />
            )}

            <button onClick={doInstall} disabled={busy} className={_btn}>
              {busy ? "Installing…" : "Install"}
            </button>
          </div>
        )}

        {result && (result.error ? (
          <div className="text-red-500 text-[13px]">{result.error}</div>
        ) : (
          <div className="text-[13px] space-y-1">
            <div className="text-brand-deep dark:text-emerald-400">Installed.</div>
            <PackResultLine label="Skills" r={result.skills} />
            <PackResultLine label="Tools" r={result.tools} />
          </div>
        ))}
      </Section>
    </div>
  );
}

const PackResultLine = ({ label, r }) => {
  if (!r) return null;
  const parts = [];
  if (r.installed?.length) parts.push(`${r.installed.length} installed`);
  if (r.skipped?.length) parts.push(`${r.skipped.length} skipped`);
  if (r.failed?.length) parts.push(`${r.failed.length} failed`);
  return <div className="text-ink-soft dark:text-night-faint">{label}: {parts.join(", ") || "none"}</div>;
};
