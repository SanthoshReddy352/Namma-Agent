import { useEffect, useState } from "react";
import { clearMemory, deletePersona, exportPack, fetchConfiguredModels, fetchConfiguredProviders, fetchEnvStatus, fetchModels, fetchModelsForProvider, fetchPackItems, fetchPersona, fetchPersonas, fetchProviders, fetchSettings, generatePersona, inspectPack, installPack, packDownloadUrl, savePersona, saveConfiguredModels, saveConfiguredProviders, saveSettings, setPersona } from "../api.js";

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

const TABS = ["Providers", "Models", "Behavior", "Persona", "Browser", "Voice", "Telegram", "Packs", "Appearance", "Memory"];

export default function Settings({ onClose, theme, onThemeToggle, onMemoryCleared, onModelsChanged, onAssistantNameChanged }) {
  const [tab, setTab] = useState("Providers");
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
          {/* Left tab nav */}
          <nav className="w-40 shrink-0 border-r border-line dark:border-night-line p-2 space-y-0.5 overflow-y-auto">
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-[13.5px] transition ${tab === t ? "bg-brand-wash dark:bg-night-soft text-brand-deep dark:text-night-ink font-medium" : "text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft"}`}>
                {t}
              </button>
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

                {tab === "Voice" && (
                  <Section title="Voice" hint="Server-side Piper TTS / local STT. (The per-message read-aloud button uses your browser's own TTS and is always available.)">
                    <Toggle label="Enable Piper voice" checked={!!cur("voice.enabled", true)} onChange={(v) => setC("voice.enabled", v)} />
                  </Section>
                )}

                {tab === "Telegram" && (
                  <Section title="Telegram" hint="Chat with FRIDAY from your phone. Stored in .env.">
                    <Field label="Bot token"><Input type="password" placeholder={data.env_set?.FRIDAY_TELEGRAM_TOKEN ? "•••••• (set)" : "not set"} value={env.FRIDAY_TELEGRAM_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, FRIDAY_TELEGRAM_TOKEN: v }))} /></Field>
                    <Field label="Chat id"><Input placeholder={data.env_set?.FRIDAY_TELEGRAM_CHAT_ID ? "(set)" : "not set"} value={env.FRIDAY_TELEGRAM_CHAT_ID ?? ""} onChange={(v) => setEnv((e) => ({ ...e, FRIDAY_TELEGRAM_CHAT_ID: v }))} /></Field>
                    <Toggle label="Reply to inbound Telegram messages" checked={!!cur("comms.inbound_enabled", true)} onChange={(v) => setC("comms.inbound_enabled", v)} />
                  </Section>
                )}

                {tab === "Packs" && <PacksTab />}

                {tab === "Appearance" && (
                  <Section title="Appearance & system">
                    <Toggle label="Dark theme" checked={theme === "dark"} onChange={onThemeToggle} />
                    <Field label="Log level"><Select value={cur("logging.level", "info")} onChange={(v) => setC("logging.level", v)} options={["debug", "info", "warning", "error"]} /></Field>
                  </Section>
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

// The "Persona" tab: rename the assistant, pick a personality from a dropdown
// (each shown with a one-line identity), and create new personas — either by
// describing one and letting the assistant draft it, or by writing the
// instructions yourself. User personas live in ~/.friday/personas and can be
// deleted; the built-ins that ship with FRIDAY can't.
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
