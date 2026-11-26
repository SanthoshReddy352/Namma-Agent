// Settings → SkillsTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { SkillsMarketplace } from "../SetupUI.jsx";
import { deleteSkill, listSkills, toggleSkill } from "../../api.js";
import { get, Section, Input, SkillBadge, GroupHeader, _box } from "./shared.jsx";

export function SkillsTab() {
  const [skills, setSkills] = useState(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState({});    // category -> expanded
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

  // Review queue: approving a draft is just enabling it (it joins the catalog and
  // stops being a proposal); discarding deletes the SKILL.md from disk.
  async function approve(s) {
    setBusy((b) => ({ ...b, [s.name]: true }));
    const r = await toggleSkill(s.name, true);
    if (r?.ok)
      setSkills((list) => list.map((x) =>
        x.name === s.name ? { ...x, enabled: true, draft: false, category: "general" } : x));
    setBusy((b) => ({ ...b, [s.name]: false }));
  }

  async function discard(s) {
    setBusy((b) => ({ ...b, [s.name]: true }));
    const r = await deleteSkill(s.name);
    if (r?.ok) setSkills((list) => list.filter((x) => x.name !== s.name));
    else setBusy((b) => ({ ...b, [s.name]: false }));
  }

  if (!skills) return <div className="text-fg-subtle">Loading…</div>;

  const drafts = skills.filter((s) => s.draft);
  const draftsOpen = open.__drafts ?? true;   // the queue is the point — open by default
  const needle = q.trim().toLowerCase();
  const shown = skills.filter((s) => !s.draft && (
    !needle || s.name.toLowerCase().includes(needle) ||
    (s.description || "").toLowerCase().includes(needle) ||
    (s.category || "").toLowerCase().includes(needle)));
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

      <div>
        <GroupHeader open={open.__market ?? false} onToggle={() => setOpen((o) => ({ ...o, __market: !(o.__market ?? false) }))}
                     label="marketplace — get more skills" count={null} />
        {(open.__market ?? false) && (
          <SkillsMarketplace onInstalled={() => listSkills().then((r) => setSkills(r?.skills || []))} />
        )}
      </div>

      {drafts.length > 0 && (
        <div>
          <GroupHeader open={draftsOpen} onToggle={() => setOpen((o) => ({ ...o, __drafts: !draftsOpen }))}
                       label="drafts awaiting review" count={drafts.length} />
          {draftsOpen && (<>
          <div className="text-sm text-fg-subtle mb-2">
            Workflows the assistant noticed repeating and wrote up as playbooks. They stay
            out of its catalog until you approve one.
          </div>
          <div className="space-y-1.5">
            {drafts.map((s) => (
              <div key={s.name} className={`${_box} flex items-start justify-between gap-3`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium">{s.name}</span>
                    <SkillBadge tone="warn">draft</SkillBadge>
                  </div>
                  {s.description && (
                    <div className="text-sm text-fg-subtle mt-0.5">{s.description}</div>
                  )}
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button type="button" disabled={!!busy[s.name]} onClick={() => approve(s)}
                          className="px-2.5 py-1 rounded-md text-sm font-medium bg-brand text-white disabled:opacity-50">
                    Approve
                  </button>
                  <button type="button" disabled={!!busy[s.name]} onClick={() => discard(s)}
                          className="px-2.5 py-1 rounded-md text-sm border border-border text-fg-subtle disabled:opacity-50">
                    Discard
                  </button>
                </div>
              </div>
            ))}
          </div>
          </>)}
        </div>
      )}

      {cats.length === 0 && <div className="text-fg-subtle text-sm">No skills match “{q}”.</div>}

      {cats.map((cat) => {
        const isOpen = open[cat] ?? !!needle;   // auto-expand while searching
        return (
        <div key={cat}>
          <GroupHeader open={isOpen} onToggle={() => setOpen((o) => ({ ...o, [cat]: !isOpen }))}
                       label={cat} count={byCat[cat].length} />
          {isOpen && (
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
                    <div className="text-sm text-fg-subtle mt-0.5">{s.description}</div>
                  )}
                  {s.requires?.length > 0 && (
                    <div className="text-xs text-fg-subtle mt-1">
                      Requires: {s.requires.join(", ")}
                    </div>
                  )}
                </div>
                <button type="button" disabled={!!busy[s.name]} onClick={() => flip(s)}
                        className={`h-6 w-11 rounded-full transition relative shrink-0 mt-0.5 disabled:opacity-50 ${s.enabled ? "bg-brand" : "bg-border"}`}>
                  <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${s.enabled ? "left-[22px]" : "left-0.5"}`} />
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
