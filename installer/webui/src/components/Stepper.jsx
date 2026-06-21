import React from "react";

function Dot({ status }) {
  if (status === "done") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ok-soft text-ok">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
          <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="flex h-6 w-6 items-center justify-center">
        <svg className="animate-spin text-brand" width="18" height="18" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.18" strokeWidth="3" />
          <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-bad-soft text-bad">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
          <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  return <span className="flex h-6 w-6 items-center justify-center"><span className="h-2 w-2 rounded-full bg-line" /></span>;
}

export default function Stepper({ steps }) {
  return (
    <ul className="space-y-1">
      {steps.map((s) => {
        const active = s.status === "active";
        const pending = s.status === "pending";
        return (
          <li
            key={s.key}
            className={
              "flex items-center gap-3 rounded-xl px-3 py-2.5 transition " +
              (active ? "bg-brand-wash" : "")
            }
          >
            <Dot status={s.status} />
            <span
              className={
                "text-[15px] " +
                (pending ? "text-ink-faint" : active ? "font-medium text-ink" : "text-ink-soft")
              }
            >
              {s.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
