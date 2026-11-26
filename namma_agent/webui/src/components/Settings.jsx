import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog, IconButton, Skeleton } from "./ui/index.js";
import SaveStatus from "./ui/SaveStatus.jsx";
import { useAutosave } from "../useAutosave.js";
import { DEFAULT_SETTINGS_TAB, sectionSlug, tabForSlug } from "../settingsSections.js";
import { clearMemory, fetchProviders, fetchSettings, saveSettings } from "../api.js";
import { get, nest, deepMerge, TAB_GROUPS } from "./settings/shared.jsx";
import { TabIcon } from "./settings/icons.jsx";
import { AppearanceTab } from "./settings/AppearanceTab.jsx";
import { AboutTab } from "./settings/AboutTab.jsx";
import { RoutinesTab } from "./settings/RoutinesTab.jsx";
import { CheckpointsTab } from "./settings/CheckpointsTab.jsx";
import { WatchersTab } from "./settings/WatchersTab.jsx";
import { LearningTab } from "./settings/LearningTab.jsx";
import { StatusTab } from "./settings/StatusTab.jsx";
import { MessagingTab } from "./settings/MessagingTab.jsx";
import { SecurityTab } from "./settings/SecurityTab.jsx";
import { NotificationsTab } from "./settings/NotificationsTab.jsx";
import { PersonaTab } from "./settings/PersonaTab.jsx";
import { ModelTab } from "./settings/ModelTab.jsx";
import { BehaviorTab, BrowserTab } from "./settings/BehaviorTab.jsx";
import { SkillsTab } from "./settings/SkillsTab.jsx";
import { ToolsetsTab } from "./settings/ToolsetsTab.jsx";
import { McpTab } from "./settings/McpTab.jsx";
import { MemorySettingsTab } from "./settings/MemoryTab.jsx";
import { PacksTab } from "./settings/PacksTab.jsx";

export default function Settings({ onClose, section, onSectionChange, theme, onThemeToggle, themeName, onThemeNameChange, onMemoryCleared, onModelsChanged, onAssistantNameChanged }) {
  // The open section comes from the URL (/settings/:section) when routed; a
  // local fallback keeps the component usable on its own (tests, embeds).
  const [localTab, setLocalTab] = useState(DEFAULT_SETTINGS_TAB);
  const tab = (section && tabForSlug(section)) || (section === undefined ? localTab : DEFAULT_SETTINGS_TAB);
  const setTab = (t) => (onSectionChange ? onSectionChange(sectionSlug(t)) : setLocalTab(t));
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return TAB_GROUPS;
    return TAB_GROUPS.map((g) => ({ ...g, tabs: g.tabs.filter((t) => `${t} ${g.label}`.toLowerCase().includes(q)) }))
      .filter((g) => g.tabs.length);
  }, [query]);
  const [data, setData] = useState(null);
  const [providers, setProviders] = useState([]);  // catalog of provider TYPES
  const [cfg, setCfg] = useState({});
  const [env, setEnvState] = useState({});
  const envRef = useRef({});
  const [cleared, setCleared] = useState("");

  useEffect(() => { fetchSettings().then(setData); fetchProviders().then((p) => setProviders(p?.providers || [])); }, []);

  const cur = (path, d) => {
    const pending = path.split(".").reduce((x, k) => (x == null ? x : x[k]), cfg);
    return pending !== undefined ? pending : get(data?.config, path, d);
  };

  // Phase 9: no Save button. Config fields save ~400 ms after the last edit;
  // secrets save when their field loses focus. A failed write rolls the view
  // back to the server's values and offers Retry.
  const auto = useAutosave((batch) => saveSettings(batch.cfg || {}, batch.env || {}), {
    merge: (a, b) => ({
      cfg: deepMerge(structuredClone(a.cfg || {}), b.cfg || {}),
      env: { ...(a.env || {}), ...(b.env || {}) },
    }),
    onSaved: (batch) => {
      const envNames = Object.keys(batch.env || {});
      setData((d) => d && ({
        ...d,
        config: deepMerge(structuredClone(d.config || {}), batch.cfg || {}),
        env_set: { ...(d.env_set || {}), ...Object.fromEntries(envNames.map((k) => [k, true])) },
      }));
      if (envNames.length) {
        // A saved secret leaves the field: it shows "•••••• (set)" instead.
        setEnvState((e) => { const n = { ...e }; envNames.forEach((k) => { if (n[k] === batch.env[k]) delete n[k]; }); envRef.current = n; return n; });
      }
      onModelsChanged?.();  // provider/key edits apply live — refresh the chat picker
    },
    onError: () => { setCfg({}); fetchSettings().then((d) => d && setData(d)); },
  });
  const setC = (path, value) => {
    setCfg((c) => deepMerge(structuredClone(c), nest(path, value)));
    auto.queue({ cfg: nest(path, value) });
  };
  // Env/secret fields keep the old `setEnv(updater)` shape for typing; the
  // write happens on blur (commitEnv) so a half-typed token is never stored.
  const setEnv = (updater) => setEnvState((e) => { const n = typeof updater === "function" ? updater(e) : updater; envRef.current = n; return n; });
  const commitEnv = (name, value) => {
    const v = value !== undefined ? value : envRef.current[name];
    if (v === undefined || v === "") return;
    auto.queue({ env: { [name]: v } }, { immediate: true });
  };
  // What every form-style section needs: the saved values, the pending edits
  // and the autosaving setters.
  const form = { data, cur, setC, env, setEnv, commitEnv };
  async function wipe(scope) { await clearMemory(scope); setCleared(scope); onMemoryCleared?.(); setTimeout(() => setCleared(""), 2500); }

  return (
    <Dialog onClose={() => { auto.flush(); onClose(); }} size="lg" labelledBy="settings-title"
            className="h-[86vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <h2 id="settings-title" className="text-md font-semibold">Settings <span className="sr-only">— {tab}</span></h2>
          <div className="flex items-center gap-3">
            <SaveStatus status={auto.status} onRetry={auto.retry} />
            <IconButton label="Close settings" onClick={() => { auto.flush(); onClose(); }} className="text-lg">×</IconButton>
          </div>
        </div>

        <div className="flex-1 flex min-h-0">
          {/* Left tab nav — grouped, icon + label (Hermes-style) */}
          <nav aria-label="Settings sections" className="w-48 shrink-0 border-r border-border p-2 overflow-y-auto">
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                   aria-label="Search settings" placeholder="Search settings"
                   onKeyDown={(e) => { if (e.key === "Enter" && groups[0]?.tabs[0]) setTab(groups[0].tabs[0]); }}
                   className="mb-2 w-full h-8 rounded-md border border-border bg-surface px-2.5 text-sm text-fg placeholder:text-fg-subtle" />
            {groups.length === 0 && <div className="px-3 py-2 text-sm text-fg-muted">No matching section</div>}
            {groups.map((g) => (
              <div key={g.label} className="mb-2 last:mb-0">
                <div className="px-3 pt-1.5 pb-1 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">{g.label}</div>
                <div className="space-y-0.5">
                  {g.tabs.map((t) => (
                    <button key={t} onClick={() => setTab(t)} aria-current={tab === t ? "page" : undefined}
                            className={`w-full flex items-center gap-2.5 text-left px-3 py-2 rounded-lg text-base transition ${tab === t ? "bg-accent-wash text-brand-deep dark:text-night-ink font-medium" : "text-fg-muted hover:bg-surface-hover"}`}>
                      <TabIcon name={t} />
                      <span>{t}</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </nav>

          {/* Right content */}
          <div className="flex-1 overflow-y-auto p-5 text-sm space-y-7">
            {!data ? <Skeleton lines={6} className="h-5 w-full" /> : (
              <>
                {tab === "Model" && <ModelTab catalog={providers} onSaved={onModelsChanged} />}

                {tab === "Behavior" && <BehaviorTab form={form} />}

                {tab === "Persona" && <PersonaTab onAssistantNameChanged={onAssistantNameChanged} />}

                {tab === "Browser" && <BrowserTab form={form} />}

                {tab === "Notifications" && <NotificationsTab />}

                {tab === "Messaging" && <MessagingTab form={form} />}

                {tab === "MCP" && <McpTab />}

                {tab === "Skills" && <SkillsTab />}

                {tab === "Toolsets" && <ToolsetsTab />}

                {tab === "Packs" && <PacksTab />}

                {tab === "Appearance" && <AppearanceTab form={form} theme={theme} onThemeToggle={onThemeToggle} themeName={themeName} onThemeNameChange={onThemeNameChange} />}

                {tab === "Memory" && <MemorySettingsTab wipe={wipe} cleared={cleared} />}

                {tab === "Security" && <SecurityTab />}
                {tab === "Checkpoints" && <CheckpointsTab />}

                {tab === "Routines" && <RoutinesTab />}
                {tab === "Watchers" && <WatchersTab />}
                {tab === "Learning" && <LearningTab />}

                {tab === "Status" && <StatusTab />}

                {tab === "About" && <AboutTab />}
              </>
            )}
          </div>
        </div>
    </Dialog>
  );
}
