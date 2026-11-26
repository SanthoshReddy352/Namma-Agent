import { useEffect, useRef, useState } from "react";
import { speak, stopSpeaking } from "../voice.js";
import { IconPlayerStopFilled, IconVolume } from "@tabler/icons-react";

// Read a message aloud (Phase 9): the operating system's own voice via the
// server (Windows SAPI, macOS `say`, espeak-ng), falling back to the browser's
// Web Speech voice. One message speaks at a time; clicking again stops it.
export default function ReadAloud({ text }) {
  const [speaking, setSpeaking] = useState(false);
  const speakingRef = useRef(false);

  useEffect(() => () => { if (speakingRef.current) stopSpeaking(); }, []);

  if (!text) return null;

  function toggle() {
    if (speakingRef.current) {
      stopSpeaking();
      speakingRef.current = false;
      setSpeaking(false);
      return;
    }
    speakingRef.current = true;
    setSpeaking(true);
    speak(text, { onEnd: () => { speakingRef.current = false; setSpeaking(false); } });
  }

  return (
    <button aria-label={speaking ? "Stop reading" : "Read aloud"} onClick={toggle} title={speaking ? "Stop reading" : "Read aloud"}
            className={`inline-flex items-center gap-1 hover:text-fg transition ${speaking ? "text-brand-deep" : ""}`}>
      {speaking ? <StopIcon /> : <SpeakerIcon />}
    </button>
  );
}

const SpeakerIcon = () => (<IconVolume size={13} stroke={2} aria-hidden="true" />);
const StopIcon = () => (<IconPlayerStopFilled size={13} aria-hidden="true" />);
