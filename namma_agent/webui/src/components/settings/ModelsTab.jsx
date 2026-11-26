// Settings → ModelsTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useRef, useState } from "react";
import SaveStatus from "../ui/SaveStatus.jsx";
import { useAutosave } from "../../useAutosave.js";
import { fetchConfiguredModels, fetchConfiguredProviders, fetchModelsForProvider, saveConfiguredModels } from "../../api.js";
import { Section } from "./shared.jsx";

// The "Models" tab: switchable model profiles. Each one just picks a configured
// provider + a model id from it — keys/URLs live on the provider, not here. These
// appear in the picker at the top of every chat (switching mid-chat = new session).
export function ModelsTab({ onSaved }) {
  const [list, setList] = useState(null);
  const [provs, setProvs] = useState([]);

  useEffect(() => {
    fetchConfiguredModels().then((r) => setList(r?.models || []));
    fetchConfiguredProviders().then((r) => setProvs(r?.providers || []));
  }, []);

  // Phase 9 autosave: saves ~600 ms after the last edit; rows without a model
  // id yet are kept on screen but not sent.
  const dirty = useRef(false);
  const auto = useAutosave(async (rows) => {
    const clean = (rows || []).filter((m) => (m.model || "").trim());
    const r = await saveConfiguredModels(clean);
    if (r?.models) {
      setList((cur) => (cur || []).map((row) => row.id ? row
        : { ...row, id: r.models.find((x) => x.model === row.model && x.provider === row.provider)?.id }));
      onSaved?.();
    }
    return r?.models ? { ok: true } : r;
  }, { delay: 600, merge: (_a, b) => b });
  useEffect(() => { if (dirty.current) auto.queue(list); }, [list]); // eslint-disable-line react-hooks/exhaustive-deps
  const update = (i, patch) => { dirty.current = true; setList((l) => l.map((row, j) => (j === i ? { ...row, ...patch } : row))); };
  const remove = (i) => { dirty.current = true; setList((l) => l.filter((_, j) => j !== i)); };
  const add = () => { dirty.current = true; setList((l) => [...(l || []), { label: "", provider: provs[0]?.id || "", model: "" }]); };

  if (list === null) return <div className="text-ink-faint">Loading…</div>;
  if (!provs.length) {
    return (
      <Section title="Your models" hint="Pick models from your providers to switch between in chat.">
        <div className="text-sm text-fg-subtle">
          Add a provider first — go to the <span className="font-medium text-fg-soft">Providers</span> tab and add one with its key. Then come back here to pick models from it.
        </div>
      </Section>
    );
  }
  return (
    <Section title="Your models"
             hint="Each model picks one of your providers + a model id from it. These are what you switch between from the composer's model picker.">
      <div className="space-y-3">
        {list.length === 0 && (
          <div className="text-sm text-fg-subtle">No models yet — add one to switch between brains in chat.</div>
        )}
        {list.map((row, i) => (
          <ModelRow key={i} row={row} providers={provs}
                    onChange={(patch) => update(i, patch)} onRemove={() => remove(i)} />
        ))}
        <button onClick={add}
                className="w-full py-2 rounded-lg border border-dashed border-border text-fg-muted hover:bg-surface-hover text-sm">
          + Add a model
        </button>
        <div className="flex items-center gap-3 pt-1 text-sm text-fg-muted">
          <SaveStatus status={auto.status} onRetry={auto.retry} />
          <span>Changes save automatically and show up in every chat's model picker.</span>
        </div>
      </div>
    </Section>
  );
}

export function ModelRow({ row, providers, onChange, onRemove }) {
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
    <div className="rounded-xl border border-border p-3 space-y-2">
      <div className="flex items-center gap-2">
        <input value={row.label || ""} onChange={(e) => onChange({ label: e.target.value })}
               placeholder="Display name (e.g. “Claude Opus”)"
               className="flex-1 rounded-lg border border-border bg-bg px-3 py-1.5 text-sm outline-none focus:border-brand" />
        <button aria-label="Remove" onClick={onRemove} title="Remove" className="px-2 text-ink-faint hover:text-red-500 text-lg leading-none">×</button>
      </div>
      <div className="flex gap-2">
        <select value={row.provider || ""} onChange={(e) => onChange({ provider: e.target.value })}
                className="w-44 rounded-lg border border-border bg-bg px-2 py-1.5 text-sm outline-none focus:border-brand">
          {providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        <input list={dlId} value={row.model || ""} onChange={(e) => onChange({ model: e.target.value })}
               placeholder={loading ? "fetching models…" : "pick or type a model id"}
               className="flex-1 rounded-lg border border-border bg-bg px-3 py-1.5 text-sm outline-none focus:border-brand" />
        <datalist id={dlId}>{models.map((m) => <option key={m} value={m} />)}</datalist>
        <button aria-label="Refresh model list" onClick={load} disabled={loading} title="Refresh model list"
                className="px-2.5 rounded-lg border border-border hover:bg-surface-hover disabled:opacity-50">
          {loading ? "…" : "↻"}
        </button>
      </div>
      <div className="text-xs">
        {loading ? <span className="text-fg-subtle">Fetching…</span>
          : source === "live" ? <span className="text-success">● {models.length} models available</span>
          : <span className="text-brand-deep dark:text-amber-400">● {error || "Set this provider's key under Connections, then ↻."}</span>}
      </div>
    </div>
  );
}
