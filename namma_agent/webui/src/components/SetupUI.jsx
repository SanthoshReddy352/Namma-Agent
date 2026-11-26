// Phase 5 setup UI: the secure secret field + chat card, first-run provider
// onboarding, the MCP add-server wizard / status / detection, and the skills
// marketplace. Secrets only ever travel through saveSecret → the vault; nothing
// here puts a value into a message, the transcript or the model's context.
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  addMcpServer, buildMcpPreset, detectMcp, importMcp, installSkill,
  mcpCatalog, previewSkill, removeMcpServer, saveSecret,
  skillsMarket,
} from "../api.js";

import { ChatSendContext } from "../chatContexts.js";
import Logo from "./Logo.jsx";
import ModelWizard from "./setup/ModelWizard.jsx";
export { ChatSendContext };

const btn = "px-3 py-1.5 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50 text-sm";
const ghost = "px-3 py-1.5 rounded-lg border border-border hover:bg-surface-hover text-sm disabled:opacity-50";
const input = "w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-brand";
const card = "rounded-xl border border-border bg-surface-raised";
const faint = "text-fg-subtle";

const STATE_STYLE = {
  connected: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  connecting: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  disabled: "bg-surface-hover text-fg-subtle",
  unknown: "bg-surface-hover text-fg-subtle",
};
export function StateBadge({ state }) {
  const s = state || "unknown";
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-medium ${STATE_STYLE[s] || STATE_STYLE.unknown}`}>
      {s === "connecting" && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
      {s}
    </span>
  );
}

// ── secrets ──────────────────────────────────────────────────────────────────

// One credential → the vault. `onSaved(name)` fires after the server confirms.
export function SecretField({ name, label, why, url, isSet = false, onSaved, compact = false }) {
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(isSet);
  const [err, setErr] = useState("");
  useEffect(() => setSaved(isSet), [isSet]);
  async function save(e) {
    e?.preventDefault();
    if (!value.trim()) return;
    setBusy(true); setErr("");
    const r = await saveSecret(name, value.trim());
    setBusy(false);
    if (r?.ok) { setValue(""); setSaved(true); onSaved?.(name); }
    else setErr(r?.error || "Couldn't save — try again.");
  }
  return (
    <form onSubmit={save} className={compact ? "space-y-1.5" : "space-y-2"}>
      {!compact && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium">{label || name}</span>
          <code className={`text-2xs ${faint}`}>{name}</code>
          {saved && <span className="text-xs text-success">✓ saved in the vault</span>}
        </div>
      )}
      {why && !compact && <div className={`text-xs ${faint}`}>{why}</div>}
      <div className="flex gap-2">
        <input type={show ? "text" : "password"} value={value} onChange={(e) => setValue(e.target.value)}
               autoComplete="off" spellCheck={false} data-secret-input={name}
               placeholder={saved ? "Saved — paste a new value to replace it" : "Paste it here (never shown in chat)"}
               className={input + " font-mono"} />
        <button type="button" onClick={() => setShow((s) => !s)} className={ghost} title={show ? "Hide" : "Show"}>
          {show ? "Hide" : "Show"}
        </button>
        <button type="submit" disabled={busy || !value.trim()} className={btn}>{busy ? "Saving…" : "Save"}</button>
      </div>
      <div className="flex items-center gap-3 text-xs">
        {url && <a href={url} target="_blank" rel="noreferrer noopener" className="text-brand hover:underline">Get one ↗</a>}
        <span className={faint}>Stored in the encrypted vault, not in chat or config files.</span>
      </div>
      {err && <div className="text-xs text-danger">{err}</div>}
    </form>
  );
}

// The ```secret card the setup agent places in chat (request_secret).
export function SecretCard({ source }) {
  const send = useContext(ChatSendContext);
  const spec = useMemo(() => { try { return JSON.parse(source); } catch { return null; } }, [source]);
  const [isSet, setIsSet] = useState(!!spec?.set);
  useEffect(() => {
    if (!spec?.name) return;
    fetch(`/api/env_status?keys=${encodeURIComponent(spec.name)}`)
      .then((r) => r.json()).then((d) => setIsSet(!!d?.env_set?.[spec.name])).catch(() => {});
  }, [spec?.name]);
  if (!spec?.name) return <div className={`my-2 text-sm ${faint}`}>(a secure field couldn't be shown)</div>;
  return (
    <div className={`${card} my-3 p-4 not-prose`} role="group" aria-label={`Secure field for ${spec.label || spec.name}`}>
      <div className="flex items-center gap-2 mb-2 text-xs uppercase tracking-wide text-brand font-semibold">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 018 0v4" /></svg>
        Secure key field
      </div>
      <SecretField name={spec.name} label={spec.label} why={spec.why} url={spec.url} isSet={isSet}
                   onSaved={(n) => send?.(`[setup] saved ${n} to the vault.`)} />
    </div>
  );
}

// ── first-run onboarding: at least one working model ─────────────────────────


export function ProviderOnboarding({ assistantName = "Namma Agent", onDone, onOpenSettings }) {
  // Phase 9 W1: first run is the model wizard (the same one Settings → Model uses).
  return (
    <div className="fixed inset-0 z-[90] overflow-y-auto bg-bg">
      <div className="max-w-2xl mx-auto px-5 py-10">
        <Logo size={44} className="mb-4" />
        <h1 className="font-serif text-3xl mb-1 text-fg">Welcome to {assistantName}</h1>
        <p className="mb-6 text-fg-muted">
          First, connect an AI model: {assistantName}'s brain. You need at least one. You can add more
          (and MCP servers, email, Google, messaging) later in <b>setup mode</b>.
        </p>
        <ModelWizard variant="onboarding" onDone={() => onDone?.()} />
        <button onClick={onOpenSettings} className="mt-8 text-sm text-fg-muted hover:underline">
          Prefer the full settings? Open Settings → Model
        </button>
      </div>
    </div>
  );
}

function PresetForm({ preset, onCancel, onAdded }) {
  const [name, setName] = useState(preset.id);
  const [params, setParams] = useState(() => Object.fromEntries(
    (preset.params || []).map((p) => [p.key, p.default ?? (p.type === "bool" ? false : p.type === "multi" ? [] : "")]))) ;
  const [secretsSet, setSecretsSet] = useState(() => Object.fromEntries((preset.secrets || []).map((s) => [s.env, !!s.set])));
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (k, v) => setParams((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    const t = setTimeout(() => buildMcpPreset(preset.id, params, name).then(setPreview), 250);
    return () => clearTimeout(t);
  }, [preset.id, params, name]);

  const missingSecret = (preset.secrets || []).some((s) => s.required && !secretsSet[s.env]);
  async function add() {
    if (!preview?.ok) return;
    setBusy(true); setMsg(null);
    const r = await addMcpServer(preview.servers[0]);
    setBusy(false);
    if (r?.ok) onAdded?.(r);
    else setMsg((r?.errors || []).map((e) => `${e.field}: ${e.message}`).join("; ") || "Couldn't add the server.");
  }
  return (
    <div className={`${card} p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium">{preset.title}</div>
          <div className={`text-xs ${faint}`}>{preset.description}</div>
        </div>
        <button onClick={onCancel} className={ghost}>Back</button>
      </div>
      <label className="block text-sm">Server name
        <input value={name} onChange={(e) => setName(e.target.value)} className={input + " mt-1"} />
      </label>
      {(preset.params || []).map((p) => (
        <div key={p.key} className="text-sm">
          <div className="mb-1">{p.label}{p.required && <span className="text-red-500"> *</span>}</div>
          {p.type === "bool" ? (
            <label className="flex items-center gap-2"><input type="checkbox" checked={!!params[p.key]} onChange={(e) => set(p.key, e.target.checked)} /> {p.help}</label>
          ) : p.type === "multi" ? (
            <div className="flex flex-wrap gap-1.5">
              {p.options.map((o) => {
                const on = (params[p.key] || []).includes(o);
                return (
                  <button key={o} type="button" onClick={() => set(p.key, on ? params[p.key].filter((x) => x !== o) : [...(params[p.key] || []), o])}
                          className={`px-2 py-0.5 rounded-full border text-xs ${on ? "bg-brand text-white border-brand" : "border-border"}`}>{o}</button>
                );
              })}
            </div>
          ) : p.type === "paths" ? (
            <textarea rows={2} value={params[p.key]} onChange={(e) => set(p.key, e.target.value)} placeholder="One folder per line" className={input + " font-mono"} />
          ) : (
            <input value={params[p.key]} onChange={(e) => set(p.key, e.target.value)} className={input + " font-mono"} />
          )}
          {p.help && p.type !== "bool" && <div className={`mt-1 text-xs ${faint}`}>{p.help}</div>}
        </div>
      ))}
      {(preset.secrets || []).map((s) => (
        <div key={s.env} className="pt-1">
          <SecretField name={s.env} label={s.label} why={s.help} url={s.url} isSet={!!secretsSet[s.env]}
                       onSaved={() => setSecretsSet((x) => ({ ...x, [s.env]: true }))} />
        </div>
      ))}
      {preview && !preview.ok && (
        <div className="text-xs text-red-600 dark:text-red-400">{preview.errors.map((e) => e.message).join("; ")}</div>
      )}
      {preview?.ok && (
        <details className="text-xs">
          <summary className={`cursor-pointer ${faint}`}>What will run</summary>
          <pre className="mt-1 p-2 rounded-lg bg-surface-hover overflow-x-auto font-mono text-xs">{JSON.stringify(preview.servers[0], null, 2)}</pre>
        </details>
      )}
      <div className="flex items-center gap-3">
        <button onClick={add} disabled={busy || !preview?.ok || missingSecret} className={btn}>{busy ? "Adding…" : "Add & connect"}</button>
        {missingSecret && <span className={`text-xs ${faint}`}>Save the required key first.</span>}
        {msg && <span className="text-xs text-red-600 dark:text-red-400">{msg}</span>}
      </div>
    </div>
  );
}

function ImportPanel({ onAdded }) {
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState({});
  async function look(useUrl) {
    setBusy(true); setRes(null);
    setRes(await importMcp(useUrl ? null : text, useUrl ? url.trim() : ""));
    setBusy(false);
  }
  async function add(server) {
    const r = await addMcpServer(server);
    setAdded((a) => ({ ...a, [server.name]: r?.ok ? "added" : (r?.errors?.[0]?.message || "failed") }));
    if (r?.ok) onAdded?.(r);
  }
  return (
    <div className={`${card} p-4 space-y-3`}>
      <div className="font-medium">Import</div>
      <div className={`text-xs ${faint}`}>Paste a config from Claude Desktop, Cursor or VS Code, a registry <code>server.json</code>, or a URL to one.</div>
      <div className="flex gap-2">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/owner/repo  or  …/mcp.json" className={input} />
        <button onClick={() => look(true)} disabled={busy || !url.trim()} className={ghost}>Fetch</button>
      </div>
      <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
                placeholder='{"mcpServers": {"time": {"command": "uvx", "args": ["mcp-server-time"]}}}' className={input + " font-mono"} />
      <button onClick={() => look(false)} disabled={busy || !text.trim()} className={ghost}>Preview</button>
      {res && (
        <div className="space-y-2">
          {(res.errors || []).map((e, i) => <div key={i} className="text-xs text-red-600 dark:text-red-400">{e.server ? `${e.server}: ` : ""}{e.message}</div>)}
          {(res.servers || []).map((s) => (
            <div key={s.name} className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2">
              <div className="min-w-0">
                <div className="text-sm font-medium">{s.name}</div>
                <div className={`text-xs font-mono truncate ${faint}`}>{s.transport === "http" ? s.url : (s.command || []).join(" ")}</div>
              </div>
              {added[s.name] ? <span className="text-xs">{added[s.name]}</span>
                : <button onClick={() => add(s)} className={btn}>Add</button>}
            </div>
          ))}
          {(res.warnings || []).map((w, i) => <div key={i} className={`text-xs ${faint}`}>⚠ {w.server}: {w.field} — {w.message}</div>)}
        </div>
      )}
    </div>
  );
}

function DetectPanel({ onAdded }) {
  const [d, setD] = useState(null);
  useEffect(() => { detectMcp().then(setD); }, []);
  if (!d) return <div className={`text-sm ${faint}`}>Checking this machine…</div>;
  const rt = d.runtimes || {};
  return (
    <div className={`${card} p-4 space-y-3`}>
      <div className="font-medium">This machine</div>
      <div className="flex flex-wrap gap-2">
        {Object.entries(rt).map(([k, v]) => (
          <span key={k} title={v.found ? (v.version || v.path) : `${v.for} — install: ${v.install}`}
                className={`px-2 py-0.5 rounded-full text-xs ${v.found && v.daemon !== false
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                  : "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"}`}>
            {k} {v.found ? (v.daemon === false ? "· engine off" : "✓") : "✗"}
          </span>
        ))}
      </div>
      {rt.docker?.hint && <div className={`text-xs ${faint}`}>{rt.docker.hint}</div>}
      {(d.disk || []).map((x) => (
        <div key={x.path} className={`text-xs ${x.low ? "text-danger" : faint}`}>
          {x.path} — {(x.free_bytes / 1e9).toFixed(1)} GB free{x.low ? " (low: Docker images / npx downloads may fail)" : ""}
        </div>
      ))}
      {(d.importable || []).length > 0 && (
        <div>
          <div className="text-sm mb-1">Already set up in other apps:</div>
          {d.importable.map((i, n) => (
            <div key={n} className="flex items-center justify-between text-sm py-1">
              <span>{i.server.name} <span className={faint}>· {i.source}</span></span>
              <button onClick={() => addMcpServer(i.server).then((r) => r?.ok && onAdded?.(r))} disabled={!i.valid} className={ghost}>Import</button>
            </div>
          ))}
        </div>
      )}
      {(d.docker_images || []).length > 0 && (
        <div>
          <div className="text-sm mb-1">Docker MCP images:</div>
          {d.docker_images.map((i) => (
            <div key={i.image} className="flex items-center justify-between text-sm py-1">
              <span className="font-mono">{i.image} <span className={faint}>{i.size}</span></span>
              <button onClick={() => addMcpServer(i.server).then((r) => r?.ok && onAdded?.(r))} className={ghost}>Add</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// The "Add a server" area above the Servers list.
export function McpAddPanel({ onChanged }) {
  const [presets, setPresets] = useState([]);
  const [open, setOpen] = useState(null);       // preset | "import" | "detect" | null
  const [notice, setNotice] = useState("");
  useEffect(() => { mcpCatalog().then((r) => setPresets(r?.presets || [])); }, []);
  const done = (r) => { setOpen(null); setNotice(`Added “${r.server || "server"}” — connecting in the background.`); onChanged?.(); };
  if (open && typeof open === "object") return <PresetForm preset={open} onCancel={() => setOpen(null)} onAdded={done} />;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-medium mr-1">Add a server</span>
        <button onClick={() => setOpen(open === "detect" ? null : "detect")} className={ghost}>Detect on this machine</button>
        <button onClick={() => setOpen(open === "import" ? null : "import")} className={ghost}>Import / from URL</button>
      </div>
      {notice && <div role="status" className="text-sm text-emerald-600 dark:text-emerald-400">{notice}</div>}
      {open === "detect" && <DetectPanel onAdded={done} />}
      {open === "import" && <ImportPanel onAdded={done} />}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {presets.map((p) => (
          <button key={p.id} onClick={() => setOpen(p)}
                  className="text-left rounded-xl border border-border px-3 py-2.5 hover:bg-paper-soft dark:hover:bg-night-soft">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{p.title}</span>
              <span className={`text-2xs uppercase tracking-wide ${faint}`}>{p.runtime}</span>
            </div>
            <div className={`text-xs mt-0.5 ${faint}`}>{p.description}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

export const removeServer = (name) => removeMcpServer(name);

// ── skills marketplace ───────────────────────────────────────────────────────

function SkillPreview({ data, onInstalled, onClose }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  async function install() {
    setBusy(true); setMsg(null);
    const r = await installSkill(data.url, !!data.exists);
    setBusy(false);
    if (r?.ok) { setMsg({ ok: true, text: `Installed “${r.name}” — it's OFF until you enable it below.` }); onInstalled?.(r); }
    else setMsg({ ok: false, text: (r?.errors || ["Install failed."]).join("; ") });
  }
  return (
    <div className={`${card} p-4 space-y-2`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium">{data.name || "(unnamed)"}</div>
          <div className={`text-xs ${faint}`}>{data.description}</div>
          <div className={`text-xs mt-1 ${faint}`}>Licence: {data.license || "not stated"} · {data.files?.length || 0} file(s)</div>
        </div>
        <button onClick={onClose} className={ghost}>Close</button>
      </div>
      {(data.errors || []).map((e, i) => <div key={i} className="text-xs text-red-600 dark:text-red-400">✗ {e}</div>)}
      {(data.warnings || []).map((w, i) => <div key={i} className="text-xs text-amber-700 dark:text-amber-400">⚠ {w}</div>)}
      {data.files?.length > 0 && (
        <details className="text-xs"><summary className={`cursor-pointer ${faint}`}>Files</summary>
          <ul className="mt-1 font-mono text-xs">{data.files.map((f) => <li key={f.path}>{f.path} <span className={faint}>({f.bytes} B)</span></li>)}</ul>
        </details>
      )}
      {data.body_preview && (
        <details className="text-xs"><summary className={`cursor-pointer ${faint}`}>Read the instructions</summary>
          <pre className="mt-1 p-2 rounded-lg bg-surface-hover whitespace-pre-wrap text-xs max-h-64 overflow-y-auto">{data.body_preview}</pre>
        </details>
      )}
      <div className="flex items-center gap-3">
        <button onClick={install} disabled={busy || !data.ok} className={btn}>{busy ? "Installing…" : data.exists ? "Replace installed copy" : "Install (disabled)"}</button>
        {msg && <span role="status" className={`text-sm ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</span>}
      </div>
    </div>
  );
}

export function SkillsMarketplace({ onInstalled }) {
  const [idx, setIdx] = useState(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [preview, setPreview] = useState(null);
  const [q, setQ] = useState("");
  const load = () => skillsMarket().then(setIdx);
  useEffect(() => { load(); }, []);
  async function look(u) {
    setBusy(u); setPreview(null);
    const r = await previewSkill(u);
    setBusy("");
    setPreview(r || { ok: false, url: u, errors: ["No response."] });
  }
  const shown = (idx?.skills || []).filter((s) => !q || `${s.name} ${s.title} ${s.description} ${s.category}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="space-y-3">
      <div className={`text-sm ${faint}`}>
        Community skills in the Agent Skills (SKILL.md) format. Every install is previewed first and lands <b>disabled</b> — read it, then switch it on.
      </div>
      <div className="flex gap-2">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Install from URL — a GitHub skill folder or a SKILL.md link" className={input} />
        <button onClick={() => look(url.trim())} disabled={!url.trim() || !!busy} className={ghost}>{busy === url.trim() ? "Fetching…" : "Preview"}</button>
      </div>
      {preview && <SkillPreview data={preview} onClose={() => setPreview(null)} onInstalled={(r) => { load(); onInstalled?.(r); }} />}
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the catalogue" className={input} />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {shown.map((s) => (
          <div key={s.url} className="rounded-xl border border-border px-3 py-2.5 flex flex-col">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{s.title}</span>
              <span className={`text-2xs uppercase tracking-wide ${faint}`}>{s.category}</span>
            </div>
            <div className={`text-xs mt-0.5 flex-1 ${faint}`}>{s.description}</div>
            <div className="flex items-center justify-between mt-2">
              <span className={`text-2xs ${faint}`}>{s.author} · {s.license}</span>
              {s.installed ? <span className="text-xs text-success">installed</span>
                : <button onClick={() => look(s.url)} disabled={!!busy} className={ghost}>{busy === s.url ? "Fetching…" : "Preview"}</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
