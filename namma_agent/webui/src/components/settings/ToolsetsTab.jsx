// Settings → ToolsetsTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { listTools, toggleTool, toggleToolset, setToolProfile, setToolSearchMode } from "../../api.js";
import { Section, Input, SkillBadge, GroupHeader, _box } from "./shared.jsx";

// The "Toolsets" tab: every tool the assistant can call, grouped by toolset, with
// an on/off switch. Disabled tools drop out of what the model sees each turn and
// are refused if somehow called. A whole toolset can be flipped from its header.
// Destructive tools (approval-gated) are badged so it's clear what they can do.
export function ToolsetsTab() {
  const [tools, setTools] = useState(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState({});    // category -> expanded
  const [busy, setBusy] = useState({});   // name|cat -> true while a toggle is in flight
  const [meta, setMeta] = useState({ profile: "general", profiles: [], search: {} });

  useEffect(() => { listTools().then((r) => {
    setTools(r?.tools || []);
    setMeta({ profile: r?.profile || "general", profiles: r?.profiles || [], search: r?.search || {} });
  }); }, []);

  async function pickProfile(id) {
    const prev = meta.profile;
    setMeta((m) => ({ ...m, profile: id }));
    const r = await setToolProfile(id);
    if (!r?.ok) setMeta((m) => ({ ...m, profile: prev }));
  }

  async function pickSearch(mode) {
    const prev = meta.search;
    setMeta((m) => ({ ...m, search: { ...m.search, mode } }));
    const r = await setToolSearchMode(mode);
    setMeta((m) => ({ ...m, search: r?.ok ? r.search : prev }));
  }

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

  if (!tools) return <div className="text-fg-subtle">Loading…</div>;

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

      <Section title="Profile"
               hint="Which toolsets the model can see. A profile never changes your switches below — tools outside the profile are just hidden from the model (shown dimmed). Per-model tool lists (Models tab) still win.">
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Toolset profile">
          {meta.profiles.map((p) => (
            <button key={p.id} type="button" role="radio" aria-checked={meta.profile === p.id}
                    title={p.hint} onClick={() => pickProfile(p.id)}
                    className={`px-3 py-1.5 rounded-lg text-sm border transition ${meta.profile === p.id
                      ? "border-brand text-brand bg-brand/5"
                      : "border-border text-fg-muted hover:text-fg"}`}>
              {p.label}
            </button>
          ))}
        </div>
        {(() => { const p = meta.profiles.find((x) => x.id === meta.profile);
          return p ? <div className="text-xs text-fg-subtle">{p.hint}</div> : null; })()}
      </Section>

      <Section title="How tools are sent to the model"
               hint="Sending every tool's schema with each request costs thousands of tokens. With tool search, only ~17 core tools are sent and the model looks up the rest by name when it needs one.">
        <div className="space-y-1.5" role="radiogroup" aria-label="Tool loading">
          {[
            ["auto", "Automatic (recommended)", `Use tool search only when more than ${meta.search.threshold ?? 40} tools are visible.`],
            ["always", "Always use tool search", "Smallest requests; the model searches for anything beyond the core tools."],
            ["off", "Send every tool", "Largest requests; useful for debugging or very capable models with few tools."],
          ].map(([value, label, desc]) => (
            <button key={value} type="button" role="radio" aria-checked={(meta.search.mode || "auto") === value}
                    onClick={() => pickSearch(value)}
                    className={`w-full text-left rounded-lg border px-3 py-2 transition ${(meta.search.mode || "auto") === value
                      ? "border-brand bg-brand/5" : "border-border hover:bg-surface-hover"}`}>
              <div className="text-sm font-medium text-fg">{label}</div>
              <div className="text-xs text-fg-subtle">{desc}</div>
            </button>
          ))}
        </div>
      </Section>

      {cats.length === 0 && <div className="text-fg-subtle text-sm">No tools match “{q}”.</div>}

      {cats.map((cat) => {
        const items = byCat[cat];
        const allOn = items.every((t) => t.enabled);
        const isOpen = open[cat] ?? !!needle;   // auto-expand while searching
        return (
          <div key={cat}>
            <GroupHeader open={isOpen} onToggle={() => setOpen((o) => ({ ...o, [cat]: !isOpen }))}
                         label={cat} count={items.length}
                         right={
                           <button type="button" disabled={!!busy[`cat:${cat}`]} onClick={() => flipCat(cat, items)}
                                   className="text-xs text-fg-subtle hover:text-brand disabled:opacity-50">
                             {allOn ? "Disable all" : "Enable all"}
                           </button>} />
            {isOpen && (
            <div className="space-y-1.5">
              {items.map((t) => (
                <div key={t.name} className={`${_box} flex items-start justify-between gap-3 ${t.in_profile === false ? "opacity-60" : ""}`}>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium font-mono text-sm">{t.name}</span>
                      {t.destructive && <SkillBadge tone="warn">needs approval</SkillBadge>}
                      {t.unavailable && <SkillBadge>hidden — {t.unavailable}</SkillBadge>}
                      {!t.unavailable && t.in_profile === false && t.enabled && <SkillBadge>not in this profile</SkillBadge>}
                    </div>
                    {t.description && (
                      <div className="text-sm text-fg-subtle mt-0.5">{t.description}</div>
                    )}
                  </div>
                  <button type="button" disabled={!!busy[t.name]} onClick={() => flip(t)}
                          className={`h-6 w-11 rounded-full transition relative shrink-0 mt-0.5 disabled:opacity-50 ${t.enabled ? "bg-brand" : "bg-border"}`}>
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${t.enabled ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                </div>
              ))}
            </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
