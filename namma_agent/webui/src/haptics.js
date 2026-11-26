// Button-click sounds, exactly as Hermes Agent does them.
//
// Hermes Agent's desktop app (MIT © 2025 Nous Research) gives every interaction a
// short "haptic" through the `web-haptics` library (MIT) with `debug: true`. On a
// phone that vibrates; on a desktop (no vibration motor) web-haptics plays the
// same pattern as audible clicks: a filtered click per step, scaled by its
// intensity. That is the sound Hermes makes. This module ports Hermes'
// `apps/desktop/src/lib/haptics.ts` and `haptics-provider.tsx`: the same library
// version (0.0.6), the same intent table, the same 50 ms selection debounce and
// 5-per-second rate limit, and the same idle warm-up of the audio device. Credit
// is in THIRD_PARTY_NOTICES.md.
import { WebHaptics } from "web-haptics";

const airyTap = [{ duration: 16, intensity: 0.52 }];
const crispTap = [{ duration: 10, intensity: 0.92 }];
const friendlySuccess = [
  { duration: 28, intensity: 0.5 },
  { delay: 42, duration: 30, intensity: 0.68 },
  { delay: 48, duration: 38, intensity: 0.86 },
];
const softArrive = [
  { duration: 18, intensity: 0.42 },
  { delay: 36, duration: 22, intensity: 0.66 },
];
const softLeave = [
  { duration: 22, intensity: 0.58 },
  { delay: 32, duration: 16, intensity: 0.34 },
];

// Hermes' HAPTIC_INTENTS, verbatim.
export const HAPTIC_INTENTS = {
  cancel: { pattern: [{ duration: 34, intensity: 0.72 }, { delay: 54, duration: 26, intensity: 0.38 }] },
  close: { pattern: softLeave },
  crisp: { pattern: crispTap },
  error: {
    pattern: [
      { duration: 34, intensity: 0.82 },
      { delay: 42, duration: 34, intensity: 0.72 },
      { delay: 58, duration: 44, intensity: 0.86 },
    ],
  },
  open: { pattern: softArrive },
  selection: { pattern: airyTap },
  streamDone: { pattern: friendlySuccess },
  streamStart: { pattern: [{ duration: 10, intensity: 0.32 }] },
  submit: { pattern: [{ duration: 24, intensity: 0.58 }, { delay: 48, duration: 36, intensity: 0.82 }] },
  success: { pattern: friendlySuccess },
  tap: { pattern: [{ duration: 14, intensity: 0.58 }, { delay: 30, duration: 12, intensity: 0.42 }] },
  warning: { pattern: [{ duration: 34, intensity: 0.64 }, { delay: 84, duration: 42, intensity: 0.5 }] },
};

const RATE_WINDOW = 1000;
const RATE_LIMIT = 5;
let recentFires = [];
let lastSelectionAt = -Infinity;
let engine = null;

function haptics() {
  if (engine || typeof window === "undefined") return engine;
  try { engine = new WebHaptics({ debug: true, showSwitch: false }); } catch { engine = null; }
  return engine;
}

// Test seam: swap the engine (or pass null to rebuild lazily).
export function _setEngine(e) { engine = e; recentFires = []; lastSelectionAt = -Infinity; }

// Hermes' triggerHaptic: debounce selection taps, cap runaway loops.
export function triggerHaptic(intent = "selection", now = (typeof performance !== "undefined" ? performance.now() : Date.now())) {
  const config = HAPTIC_INTENTS[intent];
  if (!config) return false;
  if (intent === "selection") {
    if (now - lastSelectionAt < 50) return false;
    lastSelectionAt = now;
  }
  recentFires = recentFires.filter((t) => now - t < RATE_WINDOW);
  if (recentFires.length >= RATE_LIMIT) return false;
  recentFires.push(now);
  const h = haptics();
  if (!h) return false;
  try { Promise.resolve(h.trigger(config.pattern, config.options)).catch(() => {}); } catch { return false; }
  return true;
}

// The first AudioContext pays the audio service's spin-up (~850 ms stalls in
// Hermes' profiles), so open and close a throwaway one at idle, as Hermes does.
export function warmAudio() {
  if (typeof window === "undefined" || typeof window.AudioContext === "undefined") return;
  const run = () => { try { new window.AudioContext().close().catch(() => {}); } catch { /* no audio device */ } };
  if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(run, { timeout: 2000 });
  else setTimeout(run, 500);
}
