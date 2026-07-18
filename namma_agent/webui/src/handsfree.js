// Hands-free voice mode: continuous browser speech recognition with the
// assistant's (configurable) name as the wake word.
//
// Flow: always-on recognition → an utterance containing the wake word either
// carries the command inline ("<name>, what's on my calendar?") or arms an
// 8-second "awaiting command" window (just "<name>?" → ding → speak the ask).
// Replies are spoken with the Web Speech synthesizer; recognition is paused
// while a turn runs or while the reply is being read, so the mic never hears
// the assistant talk back to itself.
//
// Everything is browser-native (Web Speech API) — no server audio, no deps —
// matching the app's voice architecture. Degrades to unavailable when the
// browser has no SpeechRecognition (the toggle simply doesn't render).

export function handsFreeSupported() {
  return typeof window !== "undefined" &&
    ("SpeechRecognition" in window || "webkitSpeechRecognition" in window) &&
    "speechSynthesis" in window;
}

const norm = (s) =>
  (s || "").toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();

const AWAIT_MS = 8000; // how long "<name>?" keeps the command window open

/**
 * @param {() => string} wakeWord   resolves the CURRENT assistant name
 * @param {(text: string) => void} onCommand  a recognized voice command
 * @param {(state: string) => void} onState   off|listening|awaiting|speaking|denied
 */
export function createHandsFree({ wakeWord, onCommand, onState }) {
  let rec = null;
  let active = false;      // user toggled on
  let speaking = false;    // reply TTS in flight (mic paused)
  let busy = false;        // a turn is running (ignore stray speech)
  let awaiting = false;    // wake word heard, waiting for the command
  let awaitTimer = null;

  const emit = (s) => { try { onState?.(s); } catch { /* state is advisory */ } };

  function startRec() {
    if (!active || speaking || rec) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    const r = new SR();
    r.lang = "en-US";
    r.continuous = true;
    r.interimResults = false;
    r.onresult = (e) => {
      const last = e.results[e.results.length - 1];
      if (last?.isFinal) handleUtterance(last[0].transcript || "");
    };
    r.onend = () => {
      rec = null;
      // Chrome ends continuous recognition periodically — quietly restart.
      if (active && !speaking) setTimeout(startRec, 300);
    };
    r.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        active = false;
        rec = null;
        emit("denied"); // mic permission refused — surface it, stay off
      }
    };
    rec = r;
    try { r.start(); } catch { rec = null; }
  }

  function handleUtterance(raw) {
    if (!active || busy || speaking) return;
    const heard = norm(raw);
    if (!heard) return;
    if (awaiting) {
      clearTimeout(awaitTimer);
      awaiting = false;
      emit("listening");
      onCommand(raw.trim());
      return;
    }
    const wake = norm(wakeWord());
    if (!wake) return;
    const idx = heard.indexOf(wake);
    if (idx === -1) return;
    const command = heard.slice(idx + wake.length).trim();
    if (command) {
      onCommand(command);
    } else {
      // Bare wake word → open the command window for the next utterance.
      awaiting = true;
      emit("awaiting");
      awaitTimer = setTimeout(() => { awaiting = false; emit("listening"); }, AWAIT_MS);
    }
  }

  return {
    start() {
      if (active) return;
      active = true;
      emit("listening");
      startRec();
    },
    stop() {
      active = false;
      awaiting = false;
      clearTimeout(awaitTimer);
      try { rec?.stop(); } catch { /* already stopped */ }
      rec = null;
      emit("off");
    },
    get active() { return active; },
    /** The app tells us when a turn is running so mid-turn chatter is ignored. */
    setBusy(b) { busy = !!b; },
    /** Speak a reply aloud with the mic paused (no feedback loop). */
    speakReply(plainText) {
      if (!active || !plainText || !("speechSynthesis" in window)) return;
      speaking = true;
      emit("speaking");
      try { rec?.stop(); } catch { /* ok */ }
      const u = new SpeechSynthesisUtterance(plainText);
      u.rate = 1.02;
      u.onend = u.onerror = () => {
        speaking = false;
        if (active) { emit("listening"); startRec(); }
      };
      window.speechSynthesis.speak(u);
    },
  };
}
