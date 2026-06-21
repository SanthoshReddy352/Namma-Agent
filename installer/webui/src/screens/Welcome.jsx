import React from "react";
import { Wordmark, Spark } from "../components/Logo.jsx";

const Bullet = ({ children }) => (
  <li className="flex items-start gap-2.5 text-[14px] text-ink-soft">
    <Spark size={15} className="mt-0.5 shrink-0 text-brand" />
    <span>{children}</span>
  </li>
);

export default function Welcome({ defaults, installDir, onChangeDir, onInstall }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-10 text-center animate-rise">
      <Wordmark />
      <p className="mt-5 max-w-xl text-[16px] text-ink-soft">
        Your trusted AI companion. We&rsquo;ll set everything up in the background —
        it only takes a few minutes.
      </p>

      <ul className="mt-8 grid max-w-md gap-2 text-left">
        <Bullet>Installs Python, Git &amp; Node.js if they&rsquo;re missing</Bullet>
        <Bullet>Downloads the app and builds its environment</Bullet>
        <Bullet>Helps you pick an AI provider and answer a few questions</Bullet>
      </ul>

      <div className="mt-8 w-full max-w-md rounded-2xl border border-line bg-canvas-panel p-4 text-left shadow-card">
        <div className="label">Install location</div>
        <div className="flex items-center gap-3">
          <code className="min-w-0 flex-1 truncate rounded-lg bg-canvas-sink px-3 py-2 font-mono text-[13px] text-ink-soft">
            {installDir || defaults?.default_install_dir || "…"}
          </code>
          <button className="btn-ghost px-4 py-2 text-[14px]" onClick={onChangeDir}>
            Change…
          </button>
        </div>
      </div>

      <button className="btn-primary mt-9 px-8 py-3.5 text-[16px]" onClick={onInstall}>
        Install Namma Agent
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <p className="mt-3 text-[12px] text-ink-faint">Version {defaults?.version || "…"}</p>
    </div>
  );
}
