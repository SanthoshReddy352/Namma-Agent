// Interaction sounds — Phase 5.
//
// Clean, short cues on the meaningful moments of a turn (message sent, response
// complete, approval/input needed, turn failed). Every sound is *synthesised in
// the browser* with the Web Audio API rather than shipped as a bundled audio
// file: no binary assets, no third-party-asset licensing to verify, identical on
// Windows / macOS / Linux, and a few hundred bytes instead of a folder of WAVs.
//
// The completion sound is a user-pickable preset (mirrors the Hermes presets:
// Two-note comfort, Glass ping, Soft marimba, …); the other events use fixed,
// distinct cues so they're recognisable without looking. Preferences are
// client-only (like the theme) and live in localStorage — there's no server side
// to this feature.

const LS_ENABLED = "namma-sound-enabled";
const LS_PRESET = "namma-sound-preset";
const LS_VOLUME = "namma-sound-volume";
const LS_EVENTS = "namma-sound-events"; // JSON: { sent, complete, approval, input, error }

export const COMPLETION_PRESETS = [
  { id: "two-note", label: "Two-note comfort" },
  { id: "glass", label: "Glass ping" },
  { id: "marimba", label: "Soft marimba" },
  { id: "tritone", label: "Tri-tone message" },
  { id: "whoosh", label: "Airy whoosh" },
  { id: "discovery", label: "Discovery cluster" },
  { id: "online", label: "Systems online" },
  { id: "terminal", label: "IBM terminal" },
  { id: "modem", label: "Modem chirp" },
  { id: "chimes", label: "Wind chimes" },
];

// The events that can ring, each with a friendly label for the settings UI.
export const SOUND_EVENTS = [
  { id: "sent", label: "Message sent" },
  { id: "tool", label: "Tool / action step" },
  { id: "complete", label: "Response ready" },
  { id: "approval", label: "Approval needed" },
  { id: "input", label: "Input needed" },
  { id: "error", label: "Turn failed" },
];

const DEFAULT_PRESET = "two-note";
const DEFAULT_VOLUME = 0.6;

// ── Preference accessors (localStorage-backed, client-only) ──────────────────
export const soundsEnabled = () => localStorage.getItem(LS_ENABLED) !== "0"; // default on
export const setSoundsEnabled = (on) => localStorage.setItem(LS_ENABLED, on ? "1" : "0");

export const completionPreset = () => localStorage.getItem(LS_PRESET) || DEFAULT_PRESET;
export const setCompletionPreset = (id) => localStorage.setItem(LS_PRESET, id);

export const soundVolume = () => {
  const v = parseFloat(localStorage.getItem(LS_VOLUME));
  return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : DEFAULT_VOLUME;
};
export const setSoundVolume = (v) => localStorage.setItem(LS_VOLUME, String(v));

function eventPrefs() {
  try {
    return { sent: true, complete: true, approval: true, input: true, error: true, ...JSON.parse(localStorage.getItem(LS_EVENTS) || "{}") };
  } catch {
    return { sent: true, complete: true, approval: true, input: true, error: true };
  }
}
export const soundEventEnabled = (id) => eventPrefs()[id] !== false;
export const setSoundEventEnabled = (id, on) =>
  localStorage.setItem(LS_EVENTS, JSON.stringify({ ...eventPrefs(), [id]: !!on }));

// ── Web Audio plumbing ───────────────────────────────────────────────────────
let _ctx = null;
function ctx() {
  if (typeof window === "undefined") return null;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  if (!_ctx) { try { _ctx = new AC(); } catch { return null; } }
  // Browsers start the context "suspended" until a user gesture — every play
  // happens right after a click/keypress, so a resume here unlocks it.
  if (_ctx.state === "suspended") _ctx.resume().catch(() => {});
  return _ctx;
}

// Schedule a list of notes: { freq, at?, dur?, type?, gain?, to?, attack? }.
// `to` sweeps the frequency from `freq`→`to` over `dur` (for whoosh/modem). The
// whole sequence is scaled by the master volume so one slider governs loudness.
function play(notes, vol = soundVolume()) {
  const ac = ctx();
  if (!ac || vol <= 0) return;
  const t0 = ac.currentTime + 0.01;
  const master = ac.createGain();
  master.gain.value = Math.max(0, Math.min(1, vol));
  master.connect(ac.destination);
  for (const n of notes) {
    const osc = ac.createOscillator();
    const g = ac.createGain();
    osc.type = n.type || "sine";
    const at = t0 + (n.at || 0);
    const dur = n.dur || 0.2;
    osc.frequency.setValueAtTime(n.freq, at);
    if (n.to) osc.frequency.exponentialRampToValueAtTime(n.to, at + dur);
    const peak = n.gain ?? 0.22;
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(peak, at + (n.attack ?? 0.008));
    g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    osc.connect(g).connect(master);
    osc.start(at);
    osc.stop(at + dur + 0.05);
  }
}

// ── The completion presets ───────────────────────────────────────────────────
// Each returns a note schedule. A couple (chimes) randomise for a natural feel.
const PENTATONIC = [880, 987.77, 1174.66, 1318.51, 1567.98];
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

const PRESET_NOTES = {
  "two-note": () => [
    { freq: 587.33, dur: 0.16, gain: 0.22 },
    { freq: 880.0, at: 0.12, dur: 0.24, gain: 0.2 },
  ],
  glass: () => [
    { freq: 1318.51, type: "triangle", dur: 0.5, gain: 0.16 },
    { freq: 1975.53, type: "triangle", at: 0.015, dur: 0.42, gain: 0.09 },
  ],
  marimba: () => [
    { freq: 523.25, dur: 0.12, gain: 0.22 },
    { freq: 659.25, at: 0.09, dur: 0.12, gain: 0.2 },
    { freq: 783.99, at: 0.18, dur: 0.2, gain: 0.18 },
  ],
  tritone: () => [
    { freq: 783.99, dur: 0.12, gain: 0.18 },
    { freq: 1046.5, at: 0.1, dur: 0.12, gain: 0.18 },
    { freq: 1318.51, at: 0.2, dur: 0.22, gain: 0.17 },
  ],
  whoosh: () => [
    { freq: 220, to: 1320, type: "sawtooth", dur: 0.34, gain: 0.07 },
    { freq: 660, to: 1760, type: "sine", at: 0.04, dur: 0.3, gain: 0.06 },
  ],
  discovery: () => [
    { freq: 659.25, dur: 0.1, gain: 0.16 },
    { freq: 830.61, at: 0.06, dur: 0.1, gain: 0.16 },
    { freq: 987.77, at: 0.12, dur: 0.1, gain: 0.16 },
    { freq: 1244.51, at: 0.18, dur: 0.22, gain: 0.15 },
  ],
  online: () => [
    { freq: 329.63, type: "square", dur: 0.12, gain: 0.1 },
    { freq: 659.25, type: "square", at: 0.12, dur: 0.22, gain: 0.1 },
  ],
  terminal: () => [
    { freq: 880, type: "square", dur: 0.09, gain: 0.09 },
    { freq: 880, type: "square", at: 0.14, dur: 0.12, gain: 0.09 },
  ],
  modem: () => [
    { freq: 480, to: 1400, type: "square", dur: 0.12, gain: 0.07 },
    { freq: 1400, to: 600, type: "sawtooth", at: 0.13, dur: 0.16, gain: 0.06 },
    { freq: 1100, type: "square", at: 0.3, dur: 0.1, gain: 0.06 },
  ],
  chimes: () => [
    { freq: pick(PENTATONIC), type: "triangle", dur: 0.5, gain: 0.13 },
    { freq: pick(PENTATONIC), type: "triangle", at: 0.12, dur: 0.5, gain: 0.11 },
    { freq: pick(PENTATONIC), type: "triangle", at: 0.26, dur: 0.55, gain: 0.1 },
  ],
};

// Fixed cues for the non-completion events — kept short and distinct.
const EVENT_NOTES = {
  sent: () => [{ freq: 1046.5, dur: 0.07, gain: 0.1 }],
  // Intermediate step (a tool/action starting) — a very soft, quick tick so a
  // multi-step turn feels alive without becoming noisy.
  tool: () => [{ freq: 1396.91, dur: 0.045, gain: 0.05 }],
  approval: () => [
    { freq: 880, dur: 0.11, gain: 0.16 },
    { freq: 880, at: 0.16, dur: 0.14, gain: 0.16 },
  ],
  input: () => [
    { freq: 659.25, dur: 0.11, gain: 0.16 },
    { freq: 987.77, at: 0.13, dur: 0.16, gain: 0.15 },
  ],
  error: () => [
    { freq: 392, type: "triangle", dur: 0.18, gain: 0.2 },
    { freq: 293.66, type: "triangle", at: 0.14, dur: 0.28, gain: 0.2 },
  ],
};

function notesForCompletion(presetId) {
  return (PRESET_NOTES[presetId] || PRESET_NOTES[DEFAULT_PRESET])();
}

// Preview a completion preset at the current volume — always rings (ignores the
// master/per-event toggles) since it's an explicit "play this for me" action.
export function previewPreset(presetId) {
  play(notesForCompletion(presetId));
}

// Ring the cue for an interaction event, honouring the master switch + the
// per-event toggle. `complete` uses the chosen completion preset.
export function playSound(event) {
  if (!soundsEnabled() || !soundEventEnabled(event)) return;
  const notes = event === "complete" ? notesForCompletion(completionPreset()) : EVENT_NOTES[event]?.();
  if (notes) play(notes);
}
