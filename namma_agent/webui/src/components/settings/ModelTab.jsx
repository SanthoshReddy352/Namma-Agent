// Settings → Model (Phase 9 W1): Providers + Models merged, the way Hermes
// does it under Settings → Model / Connections. Top to bottom:
//   Default model — which model new chats use (W2's explicit active_model;
//                   today: the first in `models:`);
//   Add a model   — the onboarding wizard, reused;
//   Connections   — the named provider connections and their keys;
//   Your models   — the switchable model profiles.
import { useEffect, useState } from "react";
import { fetchConfiguredModels } from "../../api.js";
import { getActiveModel, setActiveModel } from "../../providerContract.js";
import ModelWizard from "../setup/ModelWizard.jsx";
import { CollapsibleSection, Section } from "./shared.jsx";
import { ProvidersTab } from "./ProvidersTab.jsx";
import { ModelsTab } from "./ModelsTab.jsx";

export function DefaultModel({ refreshKey, onChanged }) {
  const [models, setModels] = useState(null);
  const [active, setActive] = useState("");
  const [state, setState] = useState("");          // "" | "saving" | "saved" | error text
  useEffect(() => {
    fetchConfiguredModels().then((r) => setModels(r?.models || []));
    getActiveModel().then(setActive);
  }, [refreshKey]);
  async function pick(id) {
    const prev = active;
    setActive(id); setState("saving");
    const r = await setActiveModel(id);
    if (r.ok) { setState("saved"); onChanged?.(); setTimeout(() => setState(""), 1600); }
    else { setActive(prev); setState(r.error || "Couldn't save."); }
  }
  if (models === null) return <p className="text-sm text-fg-muted">Loading…</p>;
  if (!models.length) return <p className="text-sm text-fg-muted">No models yet. Add one below.</p>;
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <select aria-label="Default model" value={active} onChange={(e) => pick(e.target.value)}
              className="h-9 min-w-[16rem] rounded-md border border-border bg-surface px-2.5 text-sm text-fg">
        {models.map((m) => <option key={m.id} value={m.id}>{m.label || m.model}</option>)}
      </select>
      <span role="status" className={`text-xs ${state && state !== "saving" && state !== "saved" ? "text-danger" : "text-fg-subtle"}`}>
        {state === "saving" ? "Saving…" : state === "saved" ? "Saved" : state}
      </span>
    </div>
  );
}

export function ModelTab({ catalog, onSaved }) {
  const [refresh, setRefresh] = useState(0);
  const changed = () => { setRefresh((n) => n + 1); onSaved?.(); };
  return (
    <div className="space-y-7">
      <Section title="Default model" hint="New chats start on this model. Switch any chat from the composer's model chip.">
        <DefaultModel refreshKey={refresh} onChanged={onSaved} />
      </Section>
      <CollapsibleSection title="Add a model" hint="Pick a provider, sign in, choose a model, and test it before it's saved.">
        <ModelWizard key={refresh} variant="settings" onDone={changed} />
      </CollapsibleSection>
      <ProvidersTab key={`p${refresh}`} catalog={catalog} onSaved={changed} />
      <ModelsTab key={`m${refresh}`} onSaved={changed} />
    </div>
  );
}
