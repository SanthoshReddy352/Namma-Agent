import { useEffect, useRef, useState } from "react";
import { useNavigate, useOutletContext, useSearchParams } from "react-router-dom";
import Dialog from "../components/ui/Dialog.jsx";
import {
  createLearning, createLearningFromDocument, deleteLearning, listLearning,
} from "../api.js";
import { IconSchool, IconTrash } from "@tabler/icons-react";

const DEPTHS = [
  { id: "curious", label: "Curious", blurb: "A friendly overview — intuition over detail." },
  { id: "solid", label: "Solid", blurb: "A working understanding you can use and explain." },
  { id: "deep", label: "Deep", blurb: "Thorough — the why and the edge cases." },
  { id: "expert", label: "Expert", blurb: "Rigorous and complete, no hand-waving." },
];

// Learning Room gallery: a card per topic (progress + depth) and a "new topic"
// card. Opening a topic shows its learning-path dashboard. A `?suggest=` query
// (from a struggling chat) pre-opens the create modal with the topic filled in.
export default function LearningView() {
  const [topics, setTopics] = useState([]);
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const [seed, setSeed] = useState("");
  const navigate = useNavigate();
  const { confirmAction } = useOutletContext();

  const refresh = () => listLearning().then((r) => r?.topics && setTopics(r.topics));
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

  return (
    <>
      <header className="flex items-center px-6 h-12 border-b border-border">
        <h1 className="font-serif text-lg">Learning Room</h1>
      </header>
      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-4xl mx-auto">
          <p className="text-fg-muted mb-5 text-base">
            Pick a topic and how deep you want to go. I'll build a learning path and teach it
            clearly — simple examples, diagrams, visuals and quick checks along the way.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <button onClick={() => { setSeed(""); setCreating(true); }}
              className="h-40 rounded-2xl border border-dashed border-border grid place-items-center text-fg-muted hover:border-brand hover:text-brand-deep transition">
              <div className="text-center">
                <div className="mx-auto mb-2 h-9 w-9 rounded-full bg-brand-wash dark:bg-night-panel grid place-items-center text-brand-deep">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
                </div>
                New topic
              </div>
            </button>

            {topics.map((t) => {
              const p = t.progress || {};
              const pct = p.total ? Math.round((100 * (p.done || 0)) / p.total) : 0;
              return (
                <div key={t.id} className="group relative">
                  <button onClick={() => navigate(`/learning/${t.id}`)}
                    className="h-40 w-full text-left rounded-2xl border border-border bg-surface-raised p-4 hover:shadow-soft transition flex flex-col">
                    <div className="h-9 w-9 rounded-xl bg-accent-wash grid place-items-center text-brand-deep mb-2">
                      <IconSchool size={18} stroke={1.7} aria-hidden="true" />
                    </div>
                    <div className="font-medium truncate pr-6">{t.title}</div>
                    <div className="text-xs text-fg-subtle capitalize mb-auto">{t.depth} depth</div>
                    <div className="mt-2">
                      <div className="h-1.5 rounded-full bg-paper-sink dark:bg-night overflow-hidden">
                        <div className="h-full bg-brand rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                      <div className="text-2xs text-fg-subtle mt-1">
                        {p.total ? `${p.done || 0}/${p.total} modules` : "No path yet"}
                      </div>
                    </div>
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); removeTopic(t); }} title="Delete topic"
                    className="absolute top-3 right-3 h-7 w-7 grid place-items-center rounded-full text-ink-faint hover:text-brand-deep hover:bg-surface-press opacity-0 group-hover:opacity-100 transition">
                    <IconTrash size={15} stroke={1.8} aria-hidden="true" />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </main>

      {creating && (
        <NewTopicModal seed={seed} onClose={() => setCreating(false)}
          onCreated={(t) => { setCreating(false); refresh(); if (t?.id) navigate(`/learning/${t.id}`); }} />
      )}
    </>
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
               className="w-full rounded-lg px-3 py-2 mb-4 bg-surface-sunken border border-border outline-none focus:border-brand" />
        <label className="block text-sm text-fg-muted mb-1.5">How deep should we go?</label>
        <div className="grid grid-cols-2 gap-2 mb-4">
          {DEPTHS.map((d) => (
            <button key={d.id} onClick={() => setDepth(d.id)}
              className={`text-left rounded-xl border px-3 py-2 transition ${depth === d.id
                ? "border-brand bg-accent-wash"
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
                className="w-full rounded-xl border border-dashed border-border px-3 py-3 text-left hover:border-brand transition disabled:opacity-60">
          <div className="flex items-center gap-2.5">
            <span className="h-8 w-8 shrink-0 grid place-items-center rounded-lg bg-accent-wash text-brand-deep">
              {reading
                ? <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" /><path className="opacity-90" fill="currentColor" d="M12 2a10 10 0 0 1 10 10h-3a7 7 0 0 0-7-7V2Z" /></svg>
                : <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M12 18v-6M9 15l3 3 3-3" /></svg>}
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
          <div className="mt-3 rounded-xl border border-brand-soft bg-accent-wash px-3 py-2 text-sm text-brand-deep">
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
                  className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50">
            {busy ? "Creating…" : "Start learning"}
          </button>
        </div>
    </Dialog>
  );
}
