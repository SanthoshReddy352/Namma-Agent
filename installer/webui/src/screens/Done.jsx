import React from "react";
import { Wordmark } from "../components/Logo.jsx";

export default function Done({ installDir, onLaunch, onClose, launching, verifyState }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-10 text-center animate-rise">
      <span className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-ok-soft text-ok">
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none">
          <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>

      <Wordmark />
      <h2 className="mt-5 text-[22px] font-semibold text-ink">You&rsquo;re all set 🎉</h2>
      <p className="mt-2 max-w-md text-[14px] text-ink-soft">
        Namma Agent is installed and ready.
      </p>
      <code className="mt-3 max-w-md truncate rounded-lg bg-canvas-sink px-3 py-2 font-mono text-[12px] text-ink-soft">
        {installDir}
      </code>

      {verifyState === "checking" && (
        <p className="mt-4 text-[13px] text-ink-faint">Checking the app starts cleanly…</p>
      )}
      {verifyState === "bad" && (
        <p className="mt-4 max-w-md text-[13px] text-bad">
          The backend didn&rsquo;t respond during a quick check — Launch may take a moment on first run.
        </p>
      )}

      <button className="btn-primary mt-8 px-8 py-3.5 text-[16px]" onClick={onLaunch} disabled={launching}>
        {launching ? "Launching…" : "Launch Namma Agent"}
      </button>
      <button className="btn-ghost mt-2 px-6 py-2.5 text-[14px]" onClick={onClose}>
        Close
      </button>
    </div>
  );
}
