import { useLayoutEffect, useRef, useState } from "react";
import { uploadFile } from "../api.js";
import SelectMenu from "./ui/SelectMenu.jsx";
import { dictationEngine, startBrowserDictation, startRecording, transcribe } from "../voice.js";
import { MODES, modeById } from "../roles.js";
import RoleEmblem from "./RoleEmblem.jsx";
import { IconChevronDown, IconMicrophone, IconPaperclip, IconPlayerStopFilled, IconSend } from "@tabler/icons-react";

// Textarea never grows past this (the "net safety height") — it scrolls instead.
const MAX_H = 200;
// Flip the controls to the bottom as soon as the text needs a 2nd line. Measured
// as a ratio of the *empty* single-line height (so it's robust to font size/zoom):
// 1 line ≈ 1.0×, 2 lines ≈ 2.0×, so 1.5× cleanly means "wrapped past line one".
const EXPAND_RATIO = 1.5;

const SLASH_COMMANDS = [
  { cmd: "/new", desc: "Start a new chat" },
  { cmd: "/clear", desc: "Wipe Namma Agent's memory" },
  { cmd: "/agent", desc: "Switch to agent mode (tools + skills)" },
  { cmd: "/chat", desc: "Switch to chat mode (talk only)" },
  { cmd: "/setup", desc: "Setup mode: models, MCP, Google, email, messaging" },
  { cmd: "/help", desc: "Show available commands" },
];
const BANG_HINT = [{ cmd: "!<command>", desc: "Run a shell command, e.g. !df -h" }];

// Composer (Phase 9, Hermes layout): the text on top, a toolbar row below —
// attach, the mode list and the model chip on the left; dictation, hands-free
// and send (stop while a turn runs) on the right. Always stacked, so narrow
// windows never squeeze the text field.
export default function Composer({ onSend, onStop, busy, mode, setMode, autoFocus, name = "Namma Agent", skills = [],
                                   handsfree = false, setHandsfree, handsfreeStatus = "off", modelLabel, onOpenModelPicker }) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const fileRef = useRef(null);
  const recRef = useRef(null);
  const taRef = useRef(null);
  const oneLineRef = useRef(0); // measured height of the empty (single-line) textarea

  // Grow the textarea to fit its content (up to the safety cap) and flip to the
  // bottom-bar layout once the text wraps past the first line. useLayoutEffect
  // mutates the height *before* paint so it never flashes.
  //
  // The flip is "sticky": expanding widens the textarea (controls move below it),
  // which can re-wrap a 2-line message back to 1 line — so collapsing on height
  // would oscillate. Instead we only collapse when the field is actually empty
  // (e.g. after sending), which makes the transition stable in both directions.
  function autosize() {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    // One text line + vertical padding. An empty field is always exactly one
    // line: a placeholder that wraps in a narrow window must not grow the box
    // or summon a scrollbar.
    const cs = getComputedStyle(el);
    const lineH = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.5 || 22;
    const oneLine = Math.ceil(lineH + parseFloat(cs.paddingTop || 0) + parseFloat(cs.paddingBottom || 0));
    if (!oneLineRef.current) oneLineRef.current = oneLine;
    const content = el.value ? el.scrollHeight : oneLine;
    el.style.height = Math.min(content, MAX_H) + "px";
    el.style.overflowY = content > MAX_H ? "auto" : "hidden";
    setExpanded((prev) => {
      if (!el.value.trim()) return false; // empty → controls back on the side
      return prev || content > oneLineRef.current * EXPAND_RATIO;
    });
  }
  // Re-measure on text change *and* after an expand (the width changes with it, so
  // the height must be recomputed); the sticky logic keeps this from looping.
  useLayoutEffect(() => { autosize(); }, [text, expanded]);

  function submit() {
    if (busy) return;
    if (!text.trim() && attachments.length === 0) return;
    onSend(text, attachments);
    setText("");
    setAttachments([]);
  }

  async function onPick(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setUploading(true);
    for (const f of files) {
      const r = await uploadFile(f);
      if (r?.ok) setAttachments((a) => [...a, { name: r.name, path: r.path }]);
    }
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  // Browser-native speech-to-text (Web Speech API) — dictates into the textarea.
  // Dictation (Phase 9): record the mic and let the server transcribe it with
  // the OS engine (Windows SAPI) or the cloud endpoint; the browser's own
  // recognizer is the fallback. Click once to start, again to stop.
  const [transcribing, setTranscribing] = useState(false);
  const [dictErr, setDictErr] = useState("");
  async function record() {
    setDictErr("");
    if (recRef.current) {               // second click: stop and transcribe
      const rec = recRef.current;
      recRef.current = null;
      setRecording(false);
      if (rec.kind === "browser") { rec.handle.stop(); return; }
      setTranscribing(true);
      try {
        const wav = await rec.handle.stop();
        const { text: said } = await transcribe(wav);
        if (said) setText((v) => (v ? v + " " + said : said));
        else setDictErr("I didn't catch that. Try again a little closer to the mic.");
      } catch (e) {
        setDictErr(String(e?.message || e));
      } finally {
        setTranscribing(false);
        taRef.current?.focus();
      }
      return;
    }
    const engine = await dictationEngine();
    if (!engine) { setDictErr("Dictation isn't available here."); return; }
    try {
      if (engine === "browser") {
        const handle = startBrowserDictation({
          onText: (said) => setText((v) => (v ? v + " " + said : said)),
          onEnd: () => { setRecording(false); recRef.current = null; },
        });
        recRef.current = { kind: "browser", handle };
      } else {
        recRef.current = { kind: "server", handle: await startRecording() };
      }
      setRecording(true);
    } catch (e) {
      setDictErr(e?.name === "NotAllowedError" ? "Microphone access was blocked." : String(e?.message || e));
    }
  }


  // Command hints: show when the message begins with / or !
  let hints = null;
  if (text.startsWith("/")) {
    const typed = text.split(" ")[0].toLowerCase();
    // Built-in commands, then enabled skills: "/deep-research <topic>" runs
    // that skill's procedure for this message (the server loads it).
    hints = [
      ...SLASH_COMMANDS,
      ...skills.map((s) => ({ cmd: "/" + s.name, desc: s.description, skill: true })),
    ].filter((c) => c.cmd.toLowerCase().startsWith(typed)).slice(0, 12);
  } else if (text.startsWith("!")) {
    hints = BANG_HINT;
  }

  return (
    <div className="relative rounded-2xl border border-border/80 bg-surface-raised/80 backdrop-blur-md shadow-soft">
      {dictErr && (
        <div role="alert" className="absolute -top-8 left-2 right-2 truncate text-sm text-danger">{dictErr}</div>
      )}
      {hints && hints.length > 0 && (
        <div className="absolute bottom-full mb-2 left-0 right-0 rounded-xl border border-border bg-surface-raised shadow-pop overflow-hidden">
          {hints.map((h) => (
            <button key={h.cmd} type="button"
                    onClick={() => { if (h.cmd.includes("<")) return; setText(h.cmd + " "); }}
                    className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-surface-hover">
              <span className="font-mono text-sm text-brand-deep shrink-0">{h.cmd}</span>
              <span className="text-sm text-fg-muted truncate">{h.skill ? "Skill · " : ""}{h.desc}</span>
            </button>
          ))}
        </div>
      )}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 pt-3">
          {attachments.map((a, i) => (
            <span key={i} className="flex items-center gap-1.5 text-xs bg-surface-hover border border-border rounded-md px-2 py-1">
              📎 {a.name}
              <button onClick={() => setAttachments((x) => x.filter((_, j) => j !== i))}
                      className="text-ink-faint hover:text-ink">×</button>
            </span>
          ))}
        </div>
      )}
      {/* Short text → a single row with the controls on the side. As the text grows
          the textarea expands (up to MAX_H) and, past EXPAND_AT, the layout flips to
          a column so the controls drop to the bottom of the box. Same element order
          in both layouts, so the textarea never remounts (keeps focus while typing). */}
      <div className="p-2.5 flex flex-col gap-1">
        <input ref={fileRef} type="file" multiple className="hidden" onChange={onPick} />
        <textarea
          ref={taRef}
          value={text}
          autoFocus={autoFocus}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          rows={1}
          placeholder={mode === "chat" ? `Message ${name}…`
            : mode === "setup" ? "What should we set up?"
            : `Ask ${name} to do something…`}
          className="composer-input resize-none bg-transparent outline-none px-1.5 py-2 text-prose placeholder:text-fg-subtle overflow-y-hidden max-h-[200px] w-full"
        />
        <div className="flex items-center gap-1 w-full flex-wrap">
          <button aria-label="Attach a document" title="Attach a document" onClick={() => fileRef.current?.click()}
                  className="h-9 w-9 grid place-items-center rounded-lg text-fg-muted hover:bg-surface-hover">
            {uploading ? <span className="text-xs">…</span> : <PaperclipIcon />}
          </button>
          <ModeMenu mode={mode} setMode={setMode} />
          {onOpenModelPicker && <ModelChip label={modelLabel} onClick={onOpenModelPicker} />}
          <span className="flex-1" aria-hidden="true" />
          <button type="button" onClick={record} disabled={transcribing}
                  aria-label={recording ? "Stop dictation" : transcribing ? "Transcribing…" : "Dictate"}
                  title={recording ? "Stop and transcribe" : transcribing ? "Transcribing…" : "Dictate (your system's speech recognition)"}
                  aria-pressed={recording}
                  className={`h-9 w-9 grid place-items-center rounded-lg hover:bg-surface-hover disabled:opacity-60 ${recording ? "text-danger animate-pulse" : transcribing ? "text-brand animate-pulse" : "text-fg-muted"}`}>
            <MicIcon />
          </button>
          {busy ? (
            <button aria-label="Stop" title="Stop" onClick={onStop}
                    className="h-9 w-9 grid place-items-center rounded-lg bg-fg text-bg">
              <StopIcon />
            </button>
          ) : (
            <button aria-label="Send" title="Send" onClick={submit} disabled={!text.trim() && attachments.length === 0}
                    className="h-9 w-9 grid place-items-center rounded-lg bg-brand text-white disabled:opacity-30 hover:bg-brand-deep transition">
              <SendIcon />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// Phase 9: modes are picked from a list (Hermes-style), each shown as its
// Roman role with a one-line description. Replaces the old 3-way pill.
function RoleTile({ role, emblem, size = 22 }) {
  return (
    <span aria-hidden="true" style={{ width: size, height: size }} title={role}
          className="grid place-items-center shrink-0 rounded-md bg-accent-wash text-accent">
      <RoleEmblem role={emblem || role} size={Math.round(size * 0.72)} />
    </span>
  );
}

function ModeMenu({ mode, setMode }) {
  const options = MODES.map((m) => ({
    id: m.id, label: `${m.label} · ${m.role}`, description: m.description,
    leading: <RoleTile role={m.role} emblem={m.emblem} size={28} />,
  }));
  return (
    <SelectMenu label="Mode" value={mode} onChange={setMode} options={options}
                renderTrigger={() => {
                  const cur = modeById(mode);
                  return (<><RoleTile role={cur.role} emblem={cur.emblem} /><span className="text-fg">{cur.label}</span></>);
                }} />
  );
}

// The model chip: shows the current model and opens the model picker overlay.
function ModelChip({ label, onClick }) {
  return (
    <button type="button" onClick={onClick} aria-label={`Model: ${label || "choose a model"}`} title="Choose a model"
            className="inline-flex items-center gap-1 h-8 max-w-[180px] rounded-md px-2 text-sm text-fg-muted hover:text-fg hover:bg-surface-sunken transition-colors duration-fast">
      <span className="truncate">{label || "Choose a model"}</span>
      <IconChevronDown size={12} stroke={2} aria-hidden="true" />
    </button>
  );
}

const PaperclipIcon = () => (<IconPaperclip size={18} stroke={2} aria-hidden="true" />);
const MicIcon = () => (<IconMicrophone size={18} stroke={2} aria-hidden="true" />);
const SendIcon = () => (<IconSend size={18} stroke={2} aria-hidden="true" />);
const StopIcon = () => (<IconPlayerStopFilled size={16} aria-hidden="true" />);
