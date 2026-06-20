import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router-dom";
import {
  deleteLearning, deleteTeachingPreference, getLearning, learningModuleSession,
  learningPathSession, updateLearningPlan,
} from "../api.js";

// React Flow is the heaviest dependency in the bundle — load its chunk only
// when someone actually switches to the Flow view.
const PathFlowCanvas = lazy(() => import("../components/PathFlowCanvas.jsx"));

// The "[build path]" prefix marks these as dashboard plumbing — the chat view
// hides them when the path chat is reopened (the model still sees them).
const BUILD_PROMPT =
  "[build path] Design the complete learning path for this topic now at the target depth and call " +
  "set_learning_plan with 5–9 focused modules (each a title + a one-line summary). " +
  "Do not teach a module yet — just create the path, then reply with one short sentence.";
const modifyPrompt = (notes) =>
  "[build path] Revise the learning path based on this feedback, then call set_learning_plan with the " +
  "FULL updated ordered list of modules (preserve existing modules' ids and status where " +
  `they still apply): «${notes}». Do not teach a module yet — just update the path, then ` +
  "reply with one short sentence.";

// The Learning Room dashboard for one topic: the status-colored learning path
// (click a module → its chat thread), an editable plan of action, a progress
// summary, and an insights panel (understanding score, analysis, quiz history,
// generated diagrams/visuals). It's a teaching cockpit, not a plain list.
export default function LearningDetailView() {
  const { id } = useParams();
  const { openChat, confirmAction, learningSignal, sendToSession, connected, theme } = useOutletContext();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(false);
  const [building, setBuilding] = useState(false);
  const [modifying, setModifying] = useState(false);
  // List vs Flow path view — remembered across visits (Claude-style toggle).
  const [view, setView] = useState(() => localStorage.getItem("friday-path-view") || "list");
  useEffect(() => { localStorage.setItem("friday-path-view", view); }, [view]);
  const builtRef = useRef(false); // guards one auto-build per topic load

  const load = () => getLearning(id).then(setData);
  useEffect(() => { builtRef.current = false; setBuilding(false); load(); /* eslint-disable-next-line */ }, [id]);
  // Live refresh when the teacher updates the plan / progress / insights for THIS topic.
  useEffect(() => {
    if (learningSignal && (!learningSignal.topic_id || learningSignal.topic_id === id)) load();
    /* eslint-disable-next-line */
  }, [learningSignal]);

  // Auto-build the path the first time we see a topic with no plan (covers "build
  // on create" and any empty topic), and clear the building state once it lands.
  useEffect(() => {
    const t = data?.topic;
    if (!t) return;
    const hasPlan = (t.plan || []).length > 0;
    if (hasPlan) { setBuilding(false); builtRef.current = true; return; }
    if (connected && !builtRef.current) {
      if (sendToSession(t.session_id, BUILD_PROMPT)) { builtRef.current = true; setBuilding(true); }
    }
    /* eslint-disable-next-line */
  }, [connected, data]);

  // Safety net: never leave the "Building…" spinner stuck if the model doesn't
  // produce a plan (the plan arriving clears `building` via the effect above).
  useEffect(() => {
    if (!building) return;
    const t = setTimeout(() => setBuilding(false), 90000);
    return () => clearTimeout(t);
  }, [building]);

  if (!data) return <div className="flex-1 grid place-items-center text-ink-faint">Loading…</div>;
  if (!data.topic) {
    return (
      <div className="flex-1 grid place-items-center text-ink-faint">
        Topic not found. <button className="ml-2 text-brand-deep underline" onClick={() => navigate("/learning")}>Back</button>
      </div>
    );
  }

  const { topic, insights = {}, memory = [] } = data;
  const plan = topic.plan || [];
  const prog = topic.progress || {};
  const pct = prog.total ? Math.round((100 * (prog.done || 0)) / prog.total) : 0;
  const currentId = prog.current_module || (plan[0] && plan[0].id);

  async function openModule(m) {
    // The done-pointer only moves when the teacher's confidence gate passes, so
    // jumping into a module ahead of the current one deserves a deliberate "yes".
    const order = plan.map((x) => x.id);
    const ahead = m.status === "todo" && currentId
      && order.indexOf(m.id) > order.indexOf(currentId);
    if (ahead) {
      const ok = await confirmAction?.(
        `“${m.title}” is ahead of where you are — your current module isn't complete yet. ` +
        `Lessons build on each other, so jumping ahead may feel steeper. Open it anyway?`,
        "Jump ahead");
      if (!ok) return;
    }
    const r = await learningModuleSession(id, m.id);
    if (r?.session_id) openChat(r.session_id);
  }
  async function openPathChat() {
    const r = await learningPathSession(id);
    if (r?.session_id) openChat(r.session_id);
  }
  function buildPath(notes) {
    if (sendToSession(topic.session_id, notes ? modifyPrompt(notes) : BUILD_PROMPT)) {
      setBuilding(true);
      builtRef.current = true;
    }
  }
  function continueLearning() {
    if (!plan.length) return buildPath();           // build, don't dump into a chat
    const m = plan.find((x) => x.id === currentId) || plan[0];
    openModule(m);
  }
  async function savePlan(modules) {
    const r = await updateLearningPlan(id, modules);
    if (r?.topic) setData((d) => ({ ...d, topic: r.topic }));
    setEditing(false);
  }
  async function removeTopic() {
    const ok = await confirmAction?.("Delete this topic, its modules, chats, quizzes and visuals? This can't be undone.", "Delete topic");
    if (!ok) return;
    await deleteLearning(id);
    navigate("/learning");
  }

  return (
    <>
      <header className="flex items-center justify-between px-6 h-12 border-b border-line dark:border-night-line">
        <div className="flex items-center gap-2 text-[13px] text-ink-faint dark:text-night-faint min-w-0">
          <button onClick={() => navigate("/learning")} className="grid place-items-center h-6 w-6 rounded-full hover:bg-paper-sink dark:hover:bg-night-panel shrink-0">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6" /></svg>
          </button>
          <button onClick={() => navigate("/learning")} className="hover:text-ink dark:hover:text-night-ink shrink-0">Learning Room</button>
          <span>/</span>
          <span className="text-ink dark:text-night-ink truncate">{topic.title}</span>
        </div>
        <button onClick={removeTopic} className="text-[13px] text-ink-faint hover:text-brand-deep">Delete topic</button>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-6xl mx-auto space-y-7">
          {/* Hero — title, depth, actions, progress */}
          <div>
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
              <div className="min-w-0">
                <h1 className="font-serif text-3xl truncate">{topic.title}</h1>
                <div className="text-[13px] text-ink-soft dark:text-night-faint capitalize mt-1">{topic.depth} depth</div>
              </div>
              <div className="shrink-0 flex items-center gap-2">
                <button onClick={openPathChat}
                        title="Ask about the path, reshape it, or set standing teaching preferences"
                        className="px-4 py-2 rounded-full border border-line dark:border-night-line text-[14px] font-medium text-ink-soft dark:text-night-ink hover:border-brand hover:text-brand-deep transition inline-flex items-center gap-1.5">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-9 8.4 8.5 8.5 0 0 1-3.4-.7L3 21l1.8-5.6a8.38 8.38 0 0 1-.8-3.9 8.5 8.5 0 0 1 8.5-8.5 8.38 8.38 0 0 1 8.5 8.5Z" /></svg>
                  Path chat
                </button>
                <button onClick={continueLearning} disabled={building}
                        className="px-4 py-2 rounded-full bg-brand text-white hover:bg-brand-deep text-[14px] font-medium disabled:opacity-60 inline-flex items-center gap-2">
                  {building && <Spinner />}
                  {building ? "Building…" : plan.length ? (prog.done ? "Continue learning" : "Start learning") : "Build my path"}
                </button>
              </div>
            </div>
            {plan.length > 0 && (
              <div className="mt-5 flex items-center gap-4">
                <div className="flex-1 h-2 rounded-full bg-paper-sink dark:bg-night overflow-hidden">
                  <div className="h-full bg-brand rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
                </div>
                <div className="text-[12.5px] text-ink-faint dark:text-night-faint shrink-0 tabular-nums">
                  {prog.done || 0} / {prog.total} modules · {pct}%
                </div>
              </div>
            )}
          </div>

          {/* Learning path */}
          <section className="rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <h2 className="font-medium">Learning path</h2>
                {plan.length > 0 && <ViewToggle view={view} onChange={setView} />}
              </div>
              {plan.length > 0 && !building && (
                <div className="flex items-center gap-3">
                  <button onClick={() => setModifying(true)} className="text-[13px] text-brand-deep hover:underline">Modify my path</button>
                  {view === "list" && (
                    <button onClick={() => setEditing((e) => !e)} className="text-[13px] text-ink-soft dark:text-night-faint hover:text-ink dark:hover:text-night-ink">
                      {editing ? "Done" : "Reorder"}
                    </button>
                  )}
                </div>
              )}
            </div>

            {building ? (
              <div className="flex items-center gap-3 text-[13.5px] text-ink-soft dark:text-night-faint py-2">
                <Spinner /> Designing your learning path… this takes a few seconds.
              </div>
            ) : plan.length === 0 ? (
              <div className="text-[13.5px] text-ink-soft dark:text-night-faint">
                No path yet. Click <span className="font-medium">Build my path</span> and I'll design a
                module-by-module plan for you.
              </div>
            ) : editing && view === "list" ? (
              <PlanEditor plan={plan} onSave={savePlan} onCancel={() => setEditing(false)} />
            ) : view === "flow" ? (
              <Suspense fallback={
                <div className="h-[440px] rounded-2xl border border-line dark:border-night-line grid place-items-center text-[13px] text-ink-faint dark:text-night-faint">
                  Loading canvas…
                </div>
              }>
                <PathFlowCanvas plan={plan} currentId={currentId} onOpen={openModule}
                                dark={theme === "dark"} />
              </Suspense>
            ) : (
              <PathFlow plan={plan} currentId={currentId} onOpen={openModule} />
            )}
          </section>

          {/* Analytics — a breathing bento grid */}
          <Analytics insights={insights} memory={memory}
                     preferences={topic.preferences || []}
                     onRemovePreference={async (i) => { await deleteTeachingPreference(id, i); load(); }} />
        </div>
      </main>

      {modifying && (
        <ModifyModal onClose={() => setModifying(false)}
                     onSubmit={(notes) => { setModifying(false); buildPath(notes); }} />
      )}
    </>
  );
}

// Tell the teacher how to reshape the path; it rebuilds it for real (set_learning_plan).
function ModifyModal({ onClose, onSubmit }) {
  const [notes, setNotes] = useState("");
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-[480px] max-w-full rounded-2xl bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line shadow-pop p-5 animate-rise"
           onClick={(e) => e.stopPropagation()}>
        <h3 className="font-serif text-lg mb-1">Modify the path</h3>
        <p className="text-[13px] text-ink-soft dark:text-night-faint mb-3">
          Tell me what to change — add or drop a module, go deeper somewhere, reorder, adjust the pace.
        </p>
        <textarea autoFocus value={notes} onChange={(e) => setNotes(e.target.value)} rows={4}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSubmit(notes.trim()); }}
                  placeholder="e.g. Add a module on real-world examples, and split module 3 into two."
                  className="w-full rounded-lg px-3 py-2 bg-paper-soft dark:bg-night border border-line dark:border-night-line outline-none focus:border-brand resize-none" />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-ink-soft dark:text-night-ink hover:bg-paper-soft dark:hover:bg-night-soft">Cancel</button>
          <button onClick={() => onSubmit(notes.trim())} disabled={!notes.trim()}
                  className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-50">Rebuild path</button>
        </div>
      </div>
    </div>
  );
}

// Segmented List/Flow switch, styled like the Claude desktop mode toggle: a
// rounded track with a raised active chip that slides between segments.
function ViewToggle({ view, onChange }) {
  const seg = (id, label, icon) => {
    const active = view === id;
    return (
      <button key={id} onClick={() => onChange(id)} title={`${label} view`}
              className={`relative z-10 flex items-center gap-1.5 px-3 py-1 rounded-full text-[12.5px] font-medium transition-colors ${
                active ? "text-ink dark:text-night-ink" : "text-ink-faint dark:text-night-faint hover:text-ink-soft dark:hover:text-night-ink"}`}>
        {icon}
        {label}
      </button>
    );
  };
  return (
    <div className="relative inline-flex items-center rounded-full bg-paper-sink dark:bg-night p-0.5 border border-line dark:border-night-line">
      <span className={`absolute top-0.5 bottom-0.5 w-[calc(50%-2px)] rounded-full bg-paper-panel dark:bg-night-soft shadow-soft transition-transform duration-200 ${
        view === "flow" ? "translate-x-full" : "translate-x-0"}`} style={{ left: 2 }} />
      {seg("list", "List", (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg>
      ))}
      {seg("flow", "Flow", (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="5" cy="6" r="2.2" /><circle cx="19" cy="18" r="2.2" /><path d="M7.2 6H14a3 3 0 0 1 3 3v6.8" /></svg>
      ))}
    </div>
  );
}

const Spinner = () => (
  <svg className="animate-spin h-4 w-4 text-current" viewBox="0 0 24 24" fill="none">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
    <path className="opacity-90" fill="currentColor" d="M12 2a10 10 0 0 1 10 10h-3a7 7 0 0 0-7-7V2Z" />
  </svg>
);

// Vertical, status-colored flow: done = green, current = brand (ringed), todo = muted.
function PathFlow({ plan, currentId, onOpen }) {
  const color = (m) => m.status === "done"
    ? "bg-emerald-500 border-emerald-500 text-white"
    : m.id === currentId || m.status === "current"
      ? "bg-brand border-brand text-white ring-4 ring-brand-wash dark:ring-night-soft"
      : "bg-paper dark:bg-night border-line dark:border-night-line text-ink-faint dark:text-night-faint";
  return (
    <ol className="relative">
      {plan.map((m, i) => (
        <li key={m.id} className="relative pl-10 pb-1">
          {i < plan.length - 1 && <span className="absolute left-[15px] top-7 bottom-0 w-px bg-line dark:bg-night-line" />}
          <button onClick={() => onOpen(m)}
                  className="group w-full text-left flex items-start gap-3 rounded-xl px-2 py-2 -ml-2 hover:bg-paper-soft dark:hover:bg-night-soft transition">
            <span className={`absolute left-0 mt-0.5 h-8 w-8 grid place-items-center rounded-full border text-[12px] font-semibold ${color(m)}`}>
              {m.status === "done" ? "✓" : i + 1}
            </span>
            <span className="flex-1 min-w-0">
              <span className="block text-[14px] font-medium truncate group-hover:text-brand-deep">{m.title}</span>
              {m.summary && <span className="block text-[12.5px] text-ink-faint dark:text-night-faint line-clamp-2">{m.summary}</span>}
            </span>
            <span className="text-[11px] capitalize text-ink-faint dark:text-night-faint mt-1 shrink-0">{m.status || "todo"}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function PlanEditor({ plan, onSave, onCancel }) {
  const [mods, setMods] = useState(plan.map((m) => ({ ...m })));
  const set = (i, k, v) => setMods((a) => a.map((m, j) => (j === i ? { ...m, [k]: v } : m)));
  const move = (i, d) => setMods((a) => {
    const j = i + d; if (j < 0 || j >= a.length) return a;
    const b = [...a]; [b[i], b[j]] = [b[j], b[i]]; return b;
  });
  const remove = (i) => setMods((a) => a.filter((_, j) => j !== i));
  const add = () => setMods((a) => [...a, { id: `new-${Date.now()}`, title: "", summary: "", status: "todo" }]);

  return (
    <div className="space-y-2">
      {mods.map((m, i) => (
        <div key={m.id} className="rounded-xl border border-line dark:border-night-line p-2.5 bg-paper-soft dark:bg-night">
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-ink-faint w-5 text-center shrink-0">{i + 1}</span>
            <input value={m.title} onChange={(e) => set(i, "title", e.target.value)} placeholder="Module title"
                   className="flex-1 bg-transparent text-[14px] font-medium outline-none border-b border-transparent focus:border-brand-soft" />
            <div className="flex items-center gap-0.5 shrink-0 text-ink-faint">
              <IconBtn onClick={() => move(i, -1)} title="Up"><path d="m18 15-6-6-6 6" /></IconBtn>
              <IconBtn onClick={() => move(i, 1)} title="Down"><path d="m6 9 6 6 6-6" /></IconBtn>
              <IconBtn onClick={() => remove(i)} title="Remove"><path d="M18 6 6 18M6 6l12 12" /></IconBtn>
            </div>
          </div>
          <input value={m.summary} onChange={(e) => set(i, "summary", e.target.value)} placeholder="One-line summary"
                 className="w-full mt-1 bg-transparent text-[12.5px] text-ink-soft dark:text-night-faint outline-none pl-7" />
        </div>
      ))}
      <div className="flex items-center justify-between pt-1">
        <button onClick={add} className="text-[13px] text-brand-deep hover:underline">+ Add module</button>
        <div className="flex gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 rounded-lg text-[13px] text-ink-soft hover:bg-paper-soft dark:hover:bg-night-soft">Cancel</button>
          <button onClick={() => onSave(mods.filter((m) => m.title.trim()))}
                  className="px-3 py-1.5 rounded-lg text-[13px] bg-brand text-white hover:bg-brand-deep">Save path</button>
        </div>
      </div>
    </div>
  );
}

// ── Analytics bento ─────────────────────────────────────────────────────────
// The topic's analytics, laid out as a breathing bento grid: a few tiles of
// different spans rather than a cramped stacked rail. Each tile has a labelled
// header, generous padding, and a graceful empty state so the grid stays balanced
// even on a brand-new topic.
function Tile({ label, icon, className = "", children }) {
  return (
    <section className={`rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel p-5 ${className}`}>
      <div className="flex items-center gap-2 mb-3.5 text-[11px] font-semibold uppercase tracking-wider text-ink-faint dark:text-night-faint">
        {icon}<span>{label}</span>
      </div>
      {children}
    </section>
  );
}

function Analytics({ insights, memory = [], preferences = [], onRemovePreference }) {
  const score = insights.understanding;
  const artifacts = insights.artifacts || [];
  const strengths = insights.strengths || [];
  const gaps = insights.gaps || [];
  const empty = "text-[13px] text-ink-faint dark:text-night-faint leading-relaxed";
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Understanding — the flagship tile */}
      <Tile label="Understanding" icon={<GaugeIcon />} className="sm:col-span-2 lg:col-span-2">
        <div className="flex items-center gap-5">
          <ScoreRing value={score} size={88} />
          <div className="text-[13.5px] text-ink-soft dark:text-night-faint leading-relaxed">
            {score == null ? "I'll gauge this as we go — from your answers and the questions you ask."
              : score >= 75 ? "Strong grasp so far." : score >= 45 ? "Getting there — a few gaps to close." : "Early days — we'll build it up together."}
          </div>
        </div>
        {insights.analysis && (
          <p className="mt-4 pt-4 border-t border-line dark:border-night-line text-[13.5px] text-ink-soft dark:text-night-ink leading-relaxed">
            {insights.analysis}
          </p>
        )}
      </Tile>

      {/* Visuals & demos gallery */}
      <Tile label="Visuals & demos" icon={<ImageIcon />} className="sm:col-span-2 lg:col-span-2">
        {artifacts.length ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
            {artifacts.map((a, i) => (
              <a key={i} href={a.url} target="_blank" rel="noreferrer noopener"
                 className="group block rounded-xl border border-line dark:border-night-line overflow-hidden hover:shadow-soft hover:-translate-y-0.5 transition" title={a.title || a.kind}>
                {a.kind === "diagram" || a.kind === "image" ? (
                  <img src={a.url} alt={a.title || a.kind} loading="lazy" className="w-full h-24 object-cover bg-white" />
                ) : (
                  <div className="h-24 grid place-items-center text-[12px] font-medium text-brand-deep bg-brand-wash dark:bg-night-soft capitalize">{a.kind}</div>
                )}
                <div className="px-2.5 py-1.5 text-[11px] truncate text-ink-soft dark:text-night-faint">{a.title || a.kind}</div>
              </a>
            ))}
          </div>
        ) : <div className={empty}>No diagrams or demos yet — they'll gather here as you learn.</div>}
      </Tile>

      {/* Strengths */}
      <Tile label="Strengths" icon={<SparkIcon />} className="lg:col-span-1">
        {strengths.length ? (
          <div className="flex flex-wrap gap-1.5">
            {strengths.map((s, i) => (
              <span key={i} className="px-2.5 py-1 rounded-lg text-[12.5px] bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">{s}</span>
            ))}
          </div>
        ) : <div className={empty}>None noted yet.</div>}
      </Tile>

      {/* Gaps to shore up */}
      <Tile label="To shore up" icon={<TargetIcon />} className="lg:col-span-1">
        {gaps.length ? (
          <div className="flex flex-wrap gap-1.5">
            {gaps.map((s, i) => (
              <span key={i} className="px-2.5 py-1 rounded-lg text-[12.5px] bg-brand-wash dark:bg-night-soft text-brand-deep">{s}</span>
            ))}
          </div>
        ) : <div className={empty}>Nothing flagged.</div>}
      </Tile>

      {/* What I remember */}
      <Tile label="What I remember" icon={<BookmarkIcon />} className="sm:col-span-2 lg:col-span-2">
        {memory.length ? (
          <ul className="space-y-2 text-[13px] text-ink-soft dark:text-night-faint max-h-52 overflow-y-auto pr-1">
            {memory.map((m) => (
              <li key={m.id} className="flex gap-2.5">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-brand-soft" />
                <span className="leading-relaxed">{m.content}</span>
              </li>
            ))}
          </ul>
        ) : <div className={empty}>Durable facts about your goals and progress will collect here.</div>}
      </Tile>

      {/* Teaching preferences — full-width strip */}
      {preferences.length > 0 && (
        <Tile label="Teaching preferences" icon={<SlidersIcon />} className="sm:col-span-2 lg:col-span-4">
          <p className="-mt-1 mb-3 text-[12.5px] text-ink-faint dark:text-night-faint">
            Standing instructions you've set — applied in every module. Add more in the Path chat.
          </p>
          <div className="flex flex-wrap gap-2">
            {preferences.map((p, i) => (
              <span key={i} className="group inline-flex items-center gap-2 rounded-full pl-3.5 pr-2 py-1.5 bg-paper-soft dark:bg-night border border-line dark:border-night-line text-[12.5px]">
                {p}
                <button onClick={() => onRemovePreference?.(i)} title="Remove preference"
                        className="opacity-50 group-hover:opacity-100 text-ink-faint hover:text-brand-deep">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
                </button>
              </span>
            ))}
          </div>
        </Tile>
      )}
    </div>
  );
}

function ScoreRing({ value, size = 64 }) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  const sw = Math.max(5, Math.round(size * 0.09));
  const cc = size / 2;
  const r = cc - sw / 2 - 1;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ height: size, width: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="-rotate-90" style={{ height: size, width: size }}>
        <circle cx={cc} cy={cc} r={r} fill="none" strokeWidth={sw} className="stroke-paper-sink dark:stroke-night" />
        <circle cx={cc} cy={cc} r={r} fill="none" strokeWidth={sw} strokeLinecap="round"
                className="stroke-brand" strokeDasharray={c} strokeDashoffset={c - (c * v) / 100}
                style={{ transition: "stroke-dashoffset .6s ease" }} />
      </svg>
      <div className="absolute inset-0 grid place-items-center font-semibold" style={{ fontSize: Math.round(size * 0.26) }}>
        {value == null ? "—" : v}
      </div>
    </div>
  );
}

// Tile header icons (16px, inherit currentColor).
const _ic = { width: 15, height: 15, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" };
const GaugeIcon = () => (<svg {..._ic}><path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" /><path d="M13.4 12.6 19 7" /><path d="M6.34 17.66A8 8 0 1 1 17.66 17.66" /></svg>);
const ImageIcon = () => (<svg {..._ic}><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.5-3.5L9 20" /></svg>);
const SparkIcon = () => (<svg {..._ic}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18" /></svg>);
const TargetIcon = () => (<svg {..._ic}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.5" /></svg>);
const BookmarkIcon = () => (<svg {..._ic}><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></svg>);
const SlidersIcon = () => (<svg {..._ic}><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" /></svg>);

function IconBtn({ onClick, title, children }) {
  return (
    <button onClick={onClick} title={title} className="h-6 w-6 grid place-items-center rounded hover:bg-paper-sink dark:hover:bg-night-soft hover:text-ink dark:hover:text-night-ink">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
    </button>
  );
}
