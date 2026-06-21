import React from "react";

// The Namma "spark" mark — a four-point sparkle, rendered in the brand blue.
export function Spark({ size = 28, className = "" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
      <path
        d="M12 1.5c.5 4.2 2.3 6 6.5 6.5-4.2.5-6 2.3-6.5 6.5-.5-4.2-2.3-6-6.5-6.5 4.2-.5 6-2.3 6.5-6.5Z"
        fill="currentColor"
      />
      <path
        d="M18.5 14c.27 2.05 1.2 2.98 3.25 3.25-2.05.27-2.98 1.2-3.25 3.25-.27-2.05-1.2-2.98-3.25-3.25 2.05-.27 2.98-1.2 3.25-3.25Z"
        fill="currentColor"
        opacity="0.55"
      />
    </svg>
  );
}

// Big display wordmark used on the Welcome / Done screens.
export function Wordmark({ name = "Namma Agent" }) {
  return (
    <h1 className="font-display text-[58px] leading-none tracking-tight text-ink sm:text-[68px]">
      {name.split(" ").map((w, i) => (
        <span key={i} className={i === 0 ? "text-brand" : "text-ink"}>
          {w}
          {i === 0 ? " " : ""}
        </span>
      ))}
    </h1>
  );
}
