import { useState } from "react";
import VoiceOrb from "./VoiceOrb.jsx";

export default function Composer({ onSend, busy }) {
  const [text, setText] = useState("");

  function submit() {
    if (!text.trim()) return;
    onSend(text);
    setText("");
  }

  return (
    <div className="glass rounded-2xl p-2.5 flex items-end gap-2.5">
      <VoiceOrb busy={busy} onTranscript={(t) => t && setText((v) => (v ? v + " " + t : t))} />
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        rows={1}
        placeholder="Ask FRIDAY anything…"
        className="flex-1 resize-none bg-transparent outline-none px-2 py-2.5 text-[15px] placeholder:text-ink-50/30 max-h-40"
      />
      <button
        onClick={submit}
        disabled={!text.trim()}
        className="h-10 px-4 rounded-xl bg-glow text-white font-medium shadow-glow disabled:opacity-30 disabled:shadow-none transition"
      >
        Send
      </button>
    </div>
  );
}
