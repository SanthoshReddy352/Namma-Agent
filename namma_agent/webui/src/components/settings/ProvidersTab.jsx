// Settings → ProvidersTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useRef, useState } from "react";
import SaveStatus from "../ui/SaveStatus.jsx";
import { useAutosave } from "../../useAutosave.js";
import { fetchConfiguredProviders, fetchEnvStatus, fetchModels, saveConfiguredProviders, saveSettings } from "../../api.js";
import { suggestKeyEnv, Section } from "./shared.jsx";

// The "Providers" tab: a list of named provider connections. You configure each
// one ONCE — type, base_url, and its OWN .env key variable + value — so Opencode,
// Groq, OpenAI, … coexist with independent keys. Models (next tab) just pick one.
export function ProvidersTab({ catalog, onSaved }) {
  const [list, setList] = useState(null);
  const [keys, setKeys] = useState({});      // api_key_env -> typed value
  const [envSet, setEnvSet] = useState({});  // api_key_env -> already set in .env?

  const refreshEnv = (rows) => {
    const names = [...new Set((rows || []).map((p) => (p.api_key_env || "").trim()).filter(Boolean))];
    if (names.length) fetchEnvStatus(names).then((r) => setEnvSet((s) => ({ ...s, ...(r?.env_set || {}) })));
  };
  useEffect(() => { fetchConfiguredProviders().then((r) => { setList(r?.providers || []); refreshEnv(r?.providers || []); }); }, []);

  const update = (i, patch) => { dirty.current = true; setList((l) => l.map((row, j) => (j === i ? { ...row, ...patch } : row))); };
  const remove = (i) => { dirty.current = true; setList((l) => l.filter((_, j) => j !== i)); };
  const add = () => {
    dirty.current = true;
    const def = catalog.find((p) => p.type === "opencode") || catalog[0] || {};
    setList((l) => [...(l || []), { label: "", type: def.type || "openai_compat",
      base_url: def.base_url || "", api_key_env: def.key_env || "" }]);
  };
  // Phase 9 autosave: the list saves ~600 ms after the last edit; a key saves
  // when its field loses focus. New rows pick up their server-assigned id.
  const dirty = useRef(false);
  const auto = useAutosave(async (rows) => {
    const clean = (rows || []).filter((p) => (p.type || "").trim());
    const r = await saveConfiguredProviders(clean);
    if (r?.providers) {
      setList((cur) => (cur || []).map((row) => row.id ? row
        : { ...row, id: r.providers.find((x) => x.label === row.label && x.type === row.type)?.id }));
      refreshEnv(r.providers);
      onSaved?.();
    }
    return r?.providers ? { ok: true } : r;
  }, { delay: 600, merge: (_a, b) => b });
  useEffect(() => { if (dirty.current) auto.queue(list); }, [list]); // eslint-disable-line react-hooks/exhaustive-deps
  const keyAuto = useAutosave((ks) => saveSettings({}, ks), {
    onSaved: (ks) => {
      setEnvSet((st) => ({ ...st, ...Object.fromEntries(Object.keys(ks).map((k) => [k, true])) }));
      setKeys((cur) => { const n = { ...cur }; Object.keys(ks).forEach((k) => { if (n[k] === ks[k]) delete n[k]; }); return n; });
      onSaved?.();
    },
  });
  const commitKey = (name) => { const v = keys[name]; if (name && v) keyAuto.queue({ [name]: v }, { immediate: true }); };

  if (list === null) return <div className="text-ink-faint">Loading…</div>;
  return (
    <Section title="Connections"
             hint="Add each provider once — with its OWN API key. Opencode, Groq, OpenAI, a local server… they no longer share one key. Then pick models from them under Your models.">
      <div className="space-y-3">
        {list.length === 0 && (
          <div className="text-sm text-fg-subtle">No providers yet — add one (e.g. Opencode, then Groq) and give each its own key.</div>
        )}
        {list.map((row, i) => (
          <ProviderConnRow key={i} row={row} catalog={catalog}
                           keyValue={keys[row.api_key_env] ?? ""} keySet={!!envSet[row.api_key_env]}
                           onKey={(v) => row.api_key_env && setKeys((k) => ({ ...k, [row.api_key_env]: v }))}
                           onKeyCommit={() => commitKey(row.api_key_env)}
                           onChange={(patch) => update(i, patch)} onRemove={() => remove(i)} />
        ))}
        <button onClick={add}
                className="w-full py-2 rounded-lg border border-dashed border-border text-fg-muted hover:bg-surface-hover text-sm">
          + Add a provider
        </button>
        <div className="flex items-center gap-3 pt-1 text-sm text-fg-muted">
          <SaveStatus status={keyAuto.status === "idle" ? auto.status : keyAuto.status}
                      onRetry={keyAuto.status === "error" ? keyAuto.retry : auto.retry} />
          <span>Changes save automatically. Then pick models from these under Your models.</span>
        </div>
      </div>
    </Section>
  );
}

export function ProviderConnRow({ row, catalog, onChange, onRemove, keyValue = "", keySet = false, onKey, onKeyCommit }) {
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
    <div className="rounded-xl border border-border p-3 space-y-2">
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
               className="flex-1 rounded-lg border border-border bg-bg px-3 py-1.5 text-sm outline-none focus:border-brand" />
        <select value={row.type || ""} onChange={(e) => pickType(e.target.value)}
                className="w-44 rounded-lg border border-border bg-bg px-2 py-1.5 text-sm outline-none focus:border-brand">
          {catalog.map((p) => <option key={p.type} value={p.type}>{p.label}</option>)}
        </select>
        <button aria-label="Remove" onClick={onRemove} title="Remove" className="px-2 text-ink-faint hover:text-red-500 text-lg leading-none">×</button>
      </div>
      {(needsBase || row.base_url) && (
        <input value={row.base_url || ""} onChange={(e) => onChange({ base_url: e.target.value })}
               placeholder="Base URL, e.g. https://api.groq.com/openai/v1"
               className="w-full rounded-lg border border-border bg-bg px-3 py-1.5 text-sm outline-none focus:border-brand" />
      )}
      <div className="flex gap-2">
        <input value={row.api_key_env || ""} onChange={(e) => onChange({ api_key_env: e.target.value })}
               placeholder="API key variable" title="The .env variable that holds THIS provider's key — keep it distinct per provider (OPENAI_API_KEY, GROQ_API_KEY, …)"
               className="w-52 rounded-lg border border-border bg-bg px-3 py-1.5 text-sm font-mono outline-none focus:border-brand" />
        <input type="password" value={keyValue} onChange={(e) => onKey?.(e.target.value)} onBlur={() => onKeyCommit?.()}
               placeholder={keySet ? "•••••• (set) — type to replace" : "paste this provider's API key"}
               className="flex-1 rounded-lg border border-border bg-bg px-3 py-1.5 text-sm outline-none focus:border-brand" />
        <button onClick={testConn} disabled={testing} title="Test connection — list this provider's models"
                className="px-3 rounded-lg border border-border hover:bg-surface-hover disabled:opacity-50 text-sm">
          {testing ? "…" : "Test"}
        </button>
      </div>
      <div className="text-xs">
        {test == null ? (
          <span className="text-fg-subtle">{keySet || keyValue ? "Key ready — Test to list models, then Save." : "Add the key, then Test."}</span>
        ) : test.ok ? (
          <span className="text-success">● Connected — {test.count} models available.</span>
        ) : (
          <span className="text-brand-deep dark:text-amber-400">● {test.error || "Couldn't reach the provider — check the URL/key."}</span>
        )}
      </div>
    </div>
  );
}
