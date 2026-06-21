import React, { useMemo, useState } from "react";
import { Spark } from "../components/Logo.jsx";

export default function Provider({ providers, onSave, busy }) {
  const [pid, setPid] = useState(providers[0]?.id || "anthropic");
  const current = useMemo(() => providers.find((p) => p.id === pid) || providers[0], [providers, pid]);
  const [model, setModel] = useState(current?.model || "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(current?.base_url || "");

  const pick = (id) => {
    const p = providers.find((x) => x.id === id);
    setPid(id);
    setModel(p?.model || "");
    setBaseUrl(p?.base_url || "");
    setApiKey("");
  };

  const isCompat = pid === "openai_compat";

  const save = () => {
    const provider = { type: pid, model: model.trim() };
    if (apiKey.trim()) provider.api_key = apiKey.trim();
    if (isCompat && baseUrl.trim()) provider.base_url = baseUrl.trim();
    onSave(provider);
  };

  return (
    <div className="mx-auto flex h-full w-full max-w-lg flex-col justify-center px-10 py-8 animate-rise">
      <div className="flex items-center gap-2.5">
        <Spark size={22} className="text-brand" />
        <h2 className="text-[24px] font-semibold text-ink">Choose your AI provider</h2>
      </div>
      <p className="mt-1.5 text-[14px] text-ink-soft">
        The &ldquo;brain&rdquo; behind Namma Agent. You can change this later in Settings.
      </p>

      <div className="mt-6 space-y-4">
        <div>
          <label className="label">Provider</label>
          <select className="field appearance-none" value={pid} onChange={(e) => pick(e.target.value)}>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="label">Model</label>
          <input className="field" value={model} onChange={(e) => setModel(e.target.value)} placeholder="model name" />
        </div>

        {current?.needs_key && (
          <div>
            <label className="label">API key{!isCompat ? "" : " (if required)"}</label>
            <input
              className="field font-mono"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Paste your key — stored locally in .env"
            />
          </div>
        )}

        {isCompat && (
          <div>
            <label className="label">Base URL</label>
            <input
              className="field font-mono"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </div>
        )}
      </div>

      <div className="mt-8 flex justify-end gap-2">
        <button className="btn-ghost px-5 py-3" onClick={() => onSave(null)} disabled={busy}>
          Skip for now
        </button>
        <button className="btn-primary px-7" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Continue"}
        </button>
      </div>
    </div>
  );
}
