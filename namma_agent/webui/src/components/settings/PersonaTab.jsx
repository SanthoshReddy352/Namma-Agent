// Settings → PersonaTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useRef, useState } from "react";
import { deletePersona, fetchPersona, fetchPersonas, generatePersona, savePersona, saveSettings, setPersona } from "../../api.js";
import { _pinput, Section, _btn } from "./shared.jsx";

export function PersonaTab({ onAssistantNameChanged }) {
  const [list, setList] = useState(null);
  const [active, setActive] = useState("");
  const [name, setName] = useState("");
  const [nameSaved, setNameSaved] = useState(false);
  const savedName = useRef(null);  // last saved name, so a blur without edits writes nothing
  const [showManual, setShowManual] = useState(false);
  const blankDraft = { id: "", name: "", identity: "", tone: "", dos: "", donts: "" };
  const [draft, setDraft] = useState(blankDraft);
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const sync = () => fetchPersonas().then((r) => { if (r) setActive(r.active || ""); });
    window.addEventListener("namma-personas-changed", sync);
    fetchPersonas().then((r) => {
      if (!r) return;
      setList(r.personas || []); setActive(r.active || "");
      if (r.assistant_name) { setName(r.assistant_name); savedName.current = r.assistant_name; }
    });
    return () => window.removeEventListener("namma-personas-changed", sync);
  }, []);

  async function choosePersona(id) {
    setActive(id);
    await setPersona(id);
    window.dispatchEvent(new CustomEvent("namma-personas-changed"));   // the sidebar rail
  }
  async function saveName() {
    const n = name.trim(); if (!n || n === savedName.current) return;
    savedName.current = n;
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
    if (r) { setList(r.personas || []); setActive(r.active || active); window.dispatchEvent(new CustomEvent("namma-personas-changed")); }
  }

  if (list === null) return <div className="text-ink-faint">Loading…</div>;
  return (
    <div className="space-y-5">
      <Section title="Assistant name" hint="What your assistant is called everywhere — chat, voice, Telegram, the window title.">
        <div className="flex gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Assistant name"
                 onBlur={saveName} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                 placeholder="e.g. Heaven, Jarvis, Aria" className={_pinput} />
        </div>
        {nameSaved && <div role="status" className="text-success text-sm">Saved — applied live.</div>}
      </Section>

      <div className="border-t border-border" />

      <Section title="Persona" hint="The personality your assistant uses. Switching applies immediately.">
        <select value={active} onChange={(e) => choosePersona(e.target.value)}
                className="w-full rounded-lg border border-border bg-bg px-2 py-1.5 text-sm outline-none focus:border-brand">
          {list.map((p) => <option key={p.id} value={p.id}>{p.name}{p.identity_line ? ` — ${p.identity_line}` : ""}</option>)}
        </select>
        <div className="space-y-1.5 mt-1">
          {list.map((p) => (
            <div key={p.id} className="flex items-center gap-2 text-sm">
              <span className={`h-2 w-2 rounded-full shrink-0 ${p.id === active ? "bg-brand" : "bg-border"}`} />
              <span className="font-medium shrink-0">{p.name}</span>
              <span className="text-fg-subtle truncate flex-1">{p.identity_line}</span>
              <button onClick={() => editPersona(p.id)} title="Edit / view full instructions"
                      className="text-xs underline text-fg-subtle hover:text-fg shrink-0">
                {p.source === "user" ? "edit" : "view"}
              </button>
              {p.source === "user"
                ? <button onClick={() => remove(p.id)} title="Delete persona" className="px-1 text-ink-faint hover:text-red-500 text-base leading-none shrink-0">×</button>
                : <span className="text-2xs text-fg-subtle shrink-0">built-in</span>}
            </div>
          ))}
        </div>
      </Section>

      <div className="border-t border-border" />

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
                className="text-sm underline text-fg-subtle">
          {showManual ? "hide editor" : "or write it manually"}
        </button>

        {showManual && (
          <div className="space-y-2 rounded-xl border border-border p-3">
            <div className="text-xs text-fg-subtle">
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
        {msg && <div className="text-sm text-brand-deep dark:text-emerald-400">{msg}</div>}
      </Section>
    </div>
  );
}
