// Push-to-talk orb. Uses the browser SpeechRecognition API when available as a
// convenience; the canonical local STT path runs server-side (Phase 6).
import { useRef, useState } from "react";

export default function VoiceOrb({ onTranscript, busy }) {
  const [listening, setListening] = useState(false);
  const recRef = useRef(null);

  function toggle() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      onTranscript && onTranscript(null, "speech recognition unavailable in this view");
      return;
    }
    if (listening) {
      recRef.current && recRef.current.stop();
      return;
    }
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onresult = (e) => onTranscript(e.results[0][0].transcript);
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    rec.start();
    setListening(true);
  }

  return (
    <button
      onClick={toggle}
      title="Push to talk"
      className="relative grid place-items-center h-12 w-12 rounded-full shrink-0"
    >
      {(listening || busy) && (
        <span className="absolute inset-0 rounded-full bg-glow/40 animate-pulseRing" />
      )}
      <span
        className={`relative h-12 w-12 rounded-full grid place-items-center transition ${
          listening ? "bg-accent text-ink-900" : "bg-ink-600 text-glow-soft hover:bg-ink-700"
        }`}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 10a7 7 0 0 0 14 0M12 17v4" />
        </svg>
      </span>
    </button>
  );
}
