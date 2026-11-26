import { useEffect, useState } from "react";
import { IconPlus } from "@tabler/icons-react";
import { fetchPersonas, setPersona } from "../../api.js";

// Phase 9 W1: the sidebar's profile rail (Hermes layout). One round avatar per
// persona; the active one is ringed. Click to switch who answers; "+" opens
// Settings → Persona. Collapsed sidebars show just the active avatar.
// W4: personas with a `portrait` (the Roman coins) show it; others get a
// monogram in one of the chart tokens, picked by its id.
const TONES = ["--chart-1", "--chart-2", "--chart-3", "--chart-5", "--chart-6", "--chart-7"];

export function personaTone(id = "") {
  let h = 0;
  for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TONES[h % TONES.length];
}

export function monogram(name = "") {
  const words = String(name).trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  return (words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[1][0]).toUpperCase();
}

export function Avatar({ persona, size = 28, active = false }) {
  const tone = personaTone(persona.id);
  return persona.portrait ? (
    <img src={persona.portrait} alt="" width={size} height={size}
         className={`rounded-full object-cover ${active ? "ring-2 ring-accent ring-offset-2 ring-offset-surface-sunken" : ""}`} />
  ) : (
    <span aria-hidden="true" style={{ width: size, height: size, backgroundColor: `rgb(var(${tone}) / 0.16)`, color: `rgb(var(${tone}))` }}
          className={`grid place-items-center rounded-full text-2xs font-semibold tracking-wide ${active ? "ring-2 ring-accent ring-offset-2 ring-offset-surface-sunken" : ""}`}>
      {monogram(persona.name)}
    </span>
  );
}

export default function ProfileRail({ expanded = true, onManage }) {
  const [list, setList] = useState([]);
  const [active, setActive] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    const load = () => fetchPersonas().then((r) => { if (r) { setList(r.personas || []); setActive(r.active || ""); } });
    load();
    window.addEventListener("namma-personas-changed", load);
    return () => window.removeEventListener("namma-personas-changed", load);
  }, []);

  async function pick(id) {
    if (id === active || busy) return;
    const prev = active;
    setActive(id); setBusy(id);
    try {
      const r = await setPersona(id);
      if (r && r.ok === false) setActive(prev);
      else window.dispatchEvent(new CustomEvent("namma-personas-changed"));
    } catch { setActive(prev); }
    setBusy("");
  }

  if (!list.length) return null;
  const shown = expanded ? list : list.filter((p) => p.id === active).slice(0, 1);
  return (
    <div role="radiogroup" aria-label="Persona" data-testid="profile-rail"
         className={`flex items-center gap-2 ${expanded ? "px-1 flex-wrap" : "flex-col"}`}>
      {shown.map((p) => (
        <button key={p.id} type="button" role="radio" aria-checked={p.id === active}
                aria-label={`Persona: ${p.name}${p.title ? `, ${p.title}` : ""}`}
                title={`${p.name}${p.title ? `, ${p.title}` : ""}${p.tone ? ` — ${p.tone}` : ""}`}
                onClick={() => pick(p.id)} disabled={!!busy}
                className="rounded-full transition-transform duration-fast hover:scale-105 disabled:opacity-60">
          <Avatar persona={p} active={p.id === active} />
        </button>
      ))}
      {expanded && (
        <button type="button" onClick={onManage} aria-label="Manage personas" title="Manage personas"
                className="grid place-items-center h-7 w-7 rounded-full border border-dashed border-border text-fg-muted hover:text-fg hover:border-accent">
          <IconPlus size={14} stroke={1.8} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
