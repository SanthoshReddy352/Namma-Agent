// Settings → shared (split out of Settings.jsx, Phase 9 W1).

import { useState } from "react";
import { SETTINGS_GROUPS } from "../../settingsSections.js";
import { IconChevronRight } from "@tabler/icons-react";

// Suggest an .env variable name for a provider's key. ONLY the native providers
// (OpenAI/Anthropic/Google) use their conventional shared var; every OpenAI-
// compatible endpoint (opencode, groq, ollama, custom…) gets a DISTINCT var
// derived from its label — otherwise they'd all collide on OPENAI_API_KEY (the
// exact bug that put a Groq key into OPENAI_API_KEY).
export function suggestKeyEnv(type, label, catalog) {
  if (["openai", "anthropic", "google", "gemini"].includes(type)) {
    const c = (catalog || []).find((p) => p.type === type);
    if (c?.key_env) return c.key_env;
  }
  const slug = (label || type || "").toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "");
  return slug ? `${slug}_API_KEY` : "";
}

export const get = (o, path, d) => path.split(".").reduce((x, k) => (x == null ? x : x[k]), o) ?? d;
export function nest(path, value) {
  const out = {}; let cur = out; const ks = path.split(".");
  ks.forEach((k, i) => { if (i === ks.length - 1) cur[k] = value; else cur = cur[k] = {}; });
  return out;
}
export function deepMerge(a, b) {
  for (const k in b) {
    if (b[k] && typeof b[k] === "object" && !Array.isArray(b[k])) a[k] = deepMerge(a[k] || {}, b[k]);
    else a[k] = b[k];
  }
  return a;
}

// Hermes-style grouped settings nav: labelled sections, each an icon + label row.
// (The Voice tab was folded into Behavior; the Phase-5 Sounds tab merged into the
// new Notifications panel alongside desktop notifications.)
// Phase 6: the groups live in settingsSections.js (shared with the router and
// the command palette); each section is addressable at /settings/<section>.
export const TAB_GROUPS = SETTINGS_GROUPS;

export const agoTs = (ts) => {
  if (!ts) return "never";
  const mins = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} d ago`;
};

// ── Learning: the weekly self-review (measured self-improvement) ──────────────
export const pctFmt = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
export const numFmt = (v) => (v == null ? "–" : String(v));

export function StatCard({ label, value, prev, fmt = numFmt }) {
  const delta = value != null && prev != null && value !== prev
    ? (value > prev ? "▲" : "▼") : "";
  return (
    <div className="rounded-xl border border-border px-4 py-2.5 min-w-[130px]">
      <div className="text-xs text-fg-subtle">{label}</div>
      <div className="text-md font-semibold text-fg">
        {fmt(value)}
        {delta && <span className="ml-1.5 text-xs font-normal text-fg-subtle">{delta} was {fmt(prev)}</span>}
      </div>
    </div>
  );
}

// ── Status: every background subsystem at a glance ────────────────────────────
export const agoIso = (iso) => {
  if (!iso) return "never";
  const t = Date.parse(iso);
  return Number.isNaN(t) ? "never" : agoTs(t / 1000);
};
export const fmtTokens = (n) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n || 0);

// A Section whose body folds away behind a chevron in the title row.
export function CollapsibleSection({ title, hint, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button onClick={() => setOpen((o) => !o)}
              className="w-full flex items-center gap-2 font-medium mb-1 text-left text-fg hover:opacity-80"
              aria-expanded={open}>
        <IconChevronRight size={14} stroke={2} className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`} aria-hidden="true" />
        {title}
      </button>
      {open && hint && <div className="text-xs text-fg-subtle mb-3">{hint}</div>}
      {open && <div className="space-y-2.5">{children}</div>}
    </div>
  );
}

// A titled settings block with generous vertical rhythm.
export const Block = ({ title, hint, children }) => (
  <section className="space-y-3">
    <div>
      <h3 className="text-prose font-medium text-fg">{title}</h3>
      {hint && <p className="mt-0.5 text-xs leading-relaxed text-fg-subtle">{hint}</p>}
    </div>
    {children}
  </section>
);
// A card holding a list of toggle rows, each row comfortably padded and divided.
export const ToggleCard = ({ rows, disabled }) => (
  <div className={"rounded-xl border border-border divide-y divide-border overflow-hidden " +
    (disabled ? "opacity-50 pointer-events-none" : "")}>
    {rows.map((r) => (
      <div key={r.id} className="px-3.5 py-3"><Toggle label={r.label} checked={r.checked} onChange={r.onChange} /></div>
    ))}
  </div>
);

// The "Persona" tab: rename the assistant, pick a personality from a dropdown
// (each shown with a one-line identity), and create new personas — either by
// describing one and letting the assistant draft it, or by writing the
// instructions yourself. User personas live in ~/.namma_agent/personas and can be
// deleted; the built-ins that ship with Namma Agent can't.
export const _pinput = "w-full rounded-lg border border-border bg-bg px-3 py-1.5 text-sm outline-none focus:border-brand";

export const Section = ({ title, hint, children }) => (
  <div>
    <div className="font-medium mb-1">{title}</div>
    {hint && <div className="text-xs text-fg-subtle mb-3">{hint}</div>}
    <div className="space-y-2.5">{children}</div>
  </div>
);
export const Field = ({ label, children }) => (
  <label className="flex items-center justify-between gap-3">
    <span className="text-fg-muted">{label}</span>
    <div className="w-1/2">{children}</div>
  </label>
);
export const Input = ({ value, onChange, ...p }) => (
  <input {...p} value={value} onChange={(e) => onChange(e.target.value)}
         className="w-full rounded-lg border border-border bg-bg px-3 py-1.5 outline-none focus:border-brand" />
);
export const Select = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-lg border border-border bg-bg px-2 py-1.5 outline-none focus:border-brand">
    {options.map((o) => <option key={o} value={o}>{o}</option>)}
  </select>
);
export const Toggle = ({ label, checked, onChange }) => (
  <label className="flex items-center justify-between gap-3 cursor-pointer">
    <span className="text-fg-muted">{label}</span>
    <button type="button" onClick={() => onChange(!checked)}
            className={`h-6 w-11 rounded-full transition relative shrink-0 ${checked ? "bg-brand" : "bg-border"}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${checked ? "left-[22px]" : "left-0.5"}`} />
    </button>
  </label>
);

// The "Skills" tab: every skill (procedural playbook) with an on/off switch.
// Disabled skills drop out of the agent's catalog and use_skill refuses them.
// Skills that declare prerequisites (a CLI / env var) show what they need and are
// badged "needs setup" until those are present — they stay listed but the agent
// won't be told about them while the prerequisite is missing.
export function SkillBadge({ children, tone = "muted" }) {
  const tones = {
    muted: "bg-surface-hover text-fg-subtle",
    warn: "bg-amber-100 dark:bg-amber-500/15 text-warning",
  };
  return <span className={`px-1.5 py-0.5 rounded text-2xs font-medium ${tones[tone]}`}>{children}</span>;
}

// A right-pointing chevron that rotates down when its group is open.
export function Chevron({ open }) {
  return (
    <IconChevronRight size={13} stroke={2.2} className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`} aria-hidden="true" />
  );
}

// A clickable group header (chevron + label + count + optional right-side action)
// used to collapse/expand long lists (Skills, Toolsets, MCP server tools).
export function GroupHeader({ open, onToggle, label, count, right, mono }) {
  return (
    <div className="flex items-center justify-between mb-2">
      <button type="button" onClick={onToggle}
              className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-fg-subtle hover:text-fg">
        <Chevron open={open} />
        <span className={mono ? "font-mono normal-case" : ""}>{label}</span>
        {count != null && <span className="opacity-60">({count})</span>}
      </button>
      {right}
    </div>
  );
}

// The "Packs" tab: export your own skills/tools as a shareable .zip, and import
// someone else's. Skills are markdown (safe, auto-install); tools are Python that
// runs in-process — so each tool is shown with its source and must be approved.
export const _box = "rounded-xl border border-border p-3";
export const _btn = "px-3 py-1.5 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50";
export const _btnGhost = "px-3 py-1.5 rounded-lg border border-border hover:bg-surface-hover";
