import { useEffect, useRef, useState } from "react";
import { useNavigate, useOutletContext, useSearchParams } from "react-router-dom";
import Dialog from "../components/ui/Dialog.jsx";
import {
  createLearning, createLearningFromDocument, deleteLearning, listLearning,
} from "../api.js";
import { IconArrowRight, IconFileUpload, IconLoader2, IconPlayerPlay, IconPlus, IconSchool, IconTrash } from "@tabler/icons-react";
import PageShell, { PageAction, cardClass, timeAgo, toneFor } from "../components/shell/PageShell.jsx";

const DEPTHS = [
  { id: "curious", label: "Curious", blurb: "A friendly overview — intuition over detail." },
  { id: "solid", label: "Solid", blurb: "A working understanding you can use and explain." },
  { id: "deep", label: "Deep", blurb: "Thorough — the why and the edge cases." },
  { id: "expert", label: "Expert", blurb: "Rigorous and complete, no hand-waving." },
];
const DEPTH_TONE = { curious: "--chart-3", solid: "--chart-1", deep: "--chart-5", expert: "--chart-4" };
const SUGGESTIONS = ["How neural networks learn", "Roman history in 10 modules", "Personal finance basics", "Quantum computing, intuitively"];

export function topicProgress(t) {
  const p = t.progress || {};
  const total = p.total || (t.plan || []).length || 0;
  const done = p.done || (t.plan || []).filter((m) => m.status === "done").length || 0;
  return { done, total, pct: total ? Math.round((100 * done) / total) : 0 };
}
export const nextModule = (t) => (t.plan || []).find((m) => (m.status || "todo") !== "done") || null;

// Learning Room (Phase 9 redesign): pick up where you left off, then every
// topic as a card with its progress ring and depth. A `?suggest=` query (from a
// struggling chat) pre-opens the create dialog with the topic filled in.
export default function LearningView() {
  const [topics, setTopics] = useState(null);
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const [seed, setSeed] = useState("");
  const navigate = useNavigate();
  const { confirmAction } = useOutletContext();

  const refresh = () => listLearning().then((r) => setTopics(r?.topics || []));
  async function removeTopic(t) {
    if (!(await confirmAction?.(`Delete “${t.title}” and everything in it? This can't be undone.`, "Delete topic"))) return;
    await deleteLearning(t.id);
    refresh();
  }
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    const s = params.get("suggest");
    if (s) { setSeed(s); setCreating(true); params.delete("suggest"); setParams(params, { replace: true }); }
  }, [params, setParams]);

  const list = topics || [];
  const totals = list.reduce((a, t) => { const p = topicProgress(t); return { done: a.done + p.done, total: a.total + p.total }; }, { done: 0, total: 0 });
  const current = list.find((t) => { const p = topicProgress(t); return p.total && p.done < p.total; });
  const open = (s = "") => { setSeed(s); setCreating(true); };

  return (
    <>
      <PageShell icon={IconSchool} title="Learning Room"
                 description="Pick a topic and how deep to go. I build a learning path and teach it with simple examples, diagrams and quick checks."
                 stats={list.length ? [{ label: list.length === 1 ? "topic" : "topics", value: list.length }, { label: "modules done", value: `${totals.done}/${totals.total}` }] : []}
                 action={<PageAction icon={IconPlus} onClick={() => open("")}>New topic</PageAction>}>
        {topics !== null && list.length === 0 && <EmptyState onPick={open} />}
        {current && <ContinueCard t={current} onOpen={() => navigate(`/learning/${current.id}`)} />}
        {list.length > 0 && (
          <>
            <h2 className="mt-8 mb-3 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">All topics</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {list.map((t) => <TopicCard key={t.id} t={t} onOpen={() => navigate(`/learning/${t.id}`)} onDelete={() => removeTopic(t)} />)}
            </div>
          </>
        )}
      </PageShell>

      {creating && (
        <NewTopicModal seed={seed} onClose={() => setCreating(false)}
          onCreated={(t) => { setCreating(false); refresh(); if (t?.id) navigate(`/learning/${t.id}`); }} />
      )}
    </>
  );
}

export function ProgressRing({ pct, size = 44, tone = "--accent" }) {
  const r = (size - 6) / 2, c = 2 * Math.PI * r;
  return (
    <span className="relative inline-grid place-items-center shrink-0" style={{ width: size, height: size }}
          role="img" aria-label={`${pct}% complete`}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--border))" strokeWidth="4" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`rgb(var(${tone}))`} strokeWidth="4" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} style={{ transition: "stroke-dashoffset .6s ease" }} />
      </svg>
      <span className="absolute text-2xs font-semibold tabular-nums text-fg">{pct}%</span>
    </span>
  );
}

function ContinueCard({ t, onOpen }) {
  const p = topicProgress(t);
  const nxt = nextModule(t);
  return (
    <button type="button" onClick={onOpen} data-testid="continue-learning"
            className={`${cardClass} w-full text-left p-5 flex items-center gap-5`}>
      <ProgressRing pct={p.pct} size={64} tone={DEPTH_TONE[t.depth] || "--accent"} />
      <span className="min-w-0 flex-1">
        <span className="block text-2xs font-semibold uppercase tracking-wider text-accent">Continue learning</span>
        <span className="block mt-0.5 text-md font-semibold text-fg truncate">{t.title}</span>
        <span className="block text-sm text-fg-muted truncate">
          {nxt ? <>Up next: {nxt.title}</> : "Review what you've learned"} · {p.done}/{p.total} modules
        </span>
      </span>
      <span className="shrink-0 inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-accent text-accent-fg text-sm font-medium">
        <IconPlayerPlay size={15} stroke={1.9} aria-hidden="true" />Resume
      </span>
    </button>
  );
}

function TopicCard({ t, onOpen, onDelete }) {
  const p = topicProgress(t);
  const tone = DEPTH_TONE[t.depth] || toneFor(t.id);
  const nxt = nextModule(t);
  return (
    <div className="group relative" data-topic={t.id}>
      <button onClick={onOpen} className={`${cardClass} w-full h-44 text-left p-4 flex flex-col`}>
        <span className="flex items-start gap-3">
          <ProgressRing pct={p.pct} tone={tone} />
          <span className="min-w-0 flex-1 pr-6">
            <span className="block font-semibold text-md text-fg line-clamp-2 leading-snug">{t.title}</span>
            <span className="mt-1 inline-block text-2xs font-medium capitalize px-1.5 py-0.5 rounded-md"
                  style={{ backgroundColor: `rgb(var(${tone}) / 0.14)`, color: `rgb(var(${tone}))` }}>{t.depth}</span>
          </span>
        </span>
        <span className="mt-auto text-xs text-fg-muted truncate">
          {p.total ? (nxt ? <>Next: {nxt.title}</> : "All modules done") : "Building the path…"}
        </span>
        <span className="mt-1 flex items-center gap-2 text-2xs text-fg-subtle">
          <span>{p.total ? `${p.done}/${p.total} modules` : "No path yet"}</span>
          {t.updated_at && <span>· {timeAgo(t.updated_at)}</span>}
          <span className="ml-auto inline-flex items-center gap-0.5 text-accent opacity-0 group-hover:opacity-100 transition">
            Open<IconArrowRight size={12} stroke={2} aria-hidden="true" />
          </span>
        </span>
      </button>
      <button onClick={(e) => { e.stopPropagation(); onDelete(); }} title="Delete topic" aria-label={`Delete topic ${t.title}`}
              className="absolute top-3 right-3 h-7 w-7 grid place-items-center rounded-full text-fg-subtle hover:text-danger hover:bg-surface-press opacity-0 group-hover:opacity-100 focus:opacity-100 transition">
        <IconTrash size={15} stroke={1.8} aria-hidden="true" />
      </button>
    </div>
  );
}

function EmptyState({ onPick }) {
  return (
    <div className="rounded-2xl border border-border/80 bg-surface-raised/80 backdrop-blur-md shadow-soft text-center px-6 py-12">
      <span className="mx-auto mb-4 h-16 w-16 grid place-items-center rounded-full bg-accent-wash text-accent border border-accent/25">
        <IconSchool size={30} stroke={1.5} aria-hidden="true" />
      </span>
      <h2 className="text-md font-semibold text-fg">What do you want to learn?</h2>
      <p className="mt-1 text-sm text-fg-muted max-w-md mx-auto">Start from an idea, or upload a syllabus and I'll build the path from it.</p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((s) => (
          <button key={s} type="button" onClick={() => onPick(s)}
                  className="h-8 px-3 rounded-full border border-border bg-surface text-sm text-fg-soft hover:border-accent hover:text-fg">
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function NewTopicModal({ seed, onClose, onCreated }) {
  const [topic, setTopic] = useState(seed || "");
  const [depth, setDepth] = useState("solid");
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);   // syllabus upload in flight
  const [flagged, setFlagged] = useState(null);    // {reasons: [...]} when rejected
  const [warnings, setWarnings] = useState([]);    // non-syllabus extras (path still built)
  const fileRef = useRef(null);

  async function submit() {
    if (!topic.trim() || busy) return;
    setBusy(true);
    const r = await createLearning(topic.trim(), depth);
    onCreated(r?.topic);
  }

  // Build the path from an uploaded syllabus: the level/depth is detected from
  // the document itself, so no picker is needed on this path.
  async function uploadSyllabus(file) {
    if (!file || reading) return;
    setReading(true); setFlagged(null); setWarnings([]);
    const r = await createLearningFromDocument(file);
    setReading(false);
    if (r?.ok && r.topic) {
      if (r.warnings?.length) {
        // Let the user read the "ignored extra content" note before navigating.
        setWarnings(r.warnings);
        setTimeout(() => onCreated(r.topic), 2800);
        return;
      }
      onCreated(r.topic);
      return;
    }
    // A security flag and a transient failure are different messages — don't
    // accuse an innocent document when the analysis simply hiccuped.
    setFlagged({
      security: !!r?.flagged,
      reasons: r?.reasons?.length ? r.reasons : ["The upload failed — please try again."],
    });
  }

  return (
    <Dialog onClose={onClose} size="md" labelledBy="new-topic-title" className="p-5">
        <h3 className="font-serif text-lg mb-3" id="new-topic-title">What do you want to learn?</h3>
        <input autoFocus value={topic} onChange={(e) => setTopic(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
               placeholder="e.g. How neural networks learn"
               className="w-full rounded-lg px-3 py-2 mb-4 bg-surface-sunken border border-border outline-none focus:border-accent" />
        <label className="block text-sm text-fg-muted mb-1.5">How deep should we go?</label>
        <div className="grid grid-cols-2 gap-2 mb-4" role="radiogroup" aria-label="Depth">
          {DEPTHS.map((d) => (
            <button key={d.id} onClick={() => setDepth(d.id)} role="radio" aria-checked={depth === d.id}
              className={`text-left rounded-xl border px-3 py-2 transition ${depth === d.id
                ? "border-accent bg-accent-wash"
                : "border-border hover:bg-surface-hover"}`}>
              <div className="text-base font-medium">{d.label}</div>
              <div className="text-xs text-fg-subtle leading-snug">{d.blurb}</div>
            </button>
          ))}
        </div>

        {/* Or: build the path from a school/college syllabus document. */}
        <div className="relative flex items-center gap-2 my-3">
          <span className="flex-1 h-px bg-border" />
          <span className="text-2xs uppercase tracking-wider text-fg-subtle">or</span>
          <span className="flex-1 h-px bg-border" />
        </div>
        <input ref={fileRef} type="file" className="hidden"
               accept=".pdf,.docx,.txt,.md,.html,.pptx"
               onChange={(e) => { uploadSyllabus(e.target.files?.[0]); e.target.value = ""; }} />
        <button onClick={() => fileRef.current?.click()} disabled={reading}
                className="w-full rounded-xl border border-dashed border-border px-3 py-3 text-left hover:border-accent transition disabled:opacity-60">
          <div className="flex items-center gap-2.5">
            <span className="h-8 w-8 shrink-0 grid place-items-center rounded-lg bg-accent-wash text-accent">
              {reading
                ? <IconLoader2 size={16} className="animate-spin" aria-hidden="true" />
                : <IconFileUpload size={16} stroke={1.8} aria-hidden="true" />}
            </span>
            <span>
              <span className="block text-base font-medium">
                {reading ? "Reading your syllabus…" : "Upload a syllabus instead"}
              </span>
              <span className="block text-xs text-fg-subtle">
                School or college syllabus (PDF, DOCX, …) — I'll build the path and pick the right level automatically.
              </span>
            </span>
          </div>
        </button>
        {flagged && (
          <div className="mt-3 rounded-xl border border-warning/40 bg-accent-wash px-3 py-2 text-sm text-fg">
            <div className="font-medium mb-1">
              {flagged.security
                ? "⚠ Document flagged — no path was built."
                : "Couldn't build the path from this document — try uploading it again."}
            </div>
            <ul className="list-disc pl-4 space-y-0.5 text-fg-muted">
              {flagged.reasons.slice(0, 4).map((r, i) => <li key={i} className="line-clamp-2">{r}</li>)}
            </ul>
          </div>
        )}
        {warnings.length > 0 && (
          <div className="mt-3 text-sm text-fg-subtle">
            Note: the document also contained non-syllabus content I ignored: {warnings.join("; ")}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-fg-soft hover:bg-surface-hover">Cancel</button>
          <button onClick={submit} disabled={!topic.trim() || busy}
                  className="px-4 py-2 rounded-lg bg-accent text-accent-fg hover:opacity-90 disabled:opacity-50">
            {busy ? "Creating…" : "Start learning"}
          </button>
        </div>
    </Dialog>
  );
}
