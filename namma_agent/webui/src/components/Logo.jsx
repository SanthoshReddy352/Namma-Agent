import { useId } from "react";

// Brand mark — "Orbit Spark": a four-point spark of insight crossed by a tilted
// orbit ring. Name-independent art (no letter). Scales crisply from favicon to
// hero. `size` is px; colors come from the brand blue gradient.
export default function Logo({ size = 28, className = "", title = "" }) {
  const id = useId().replace(/:/g, "");
  const gid = `lg-${id}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={className}
      role={title ? "img" : "presentation"}
      aria-label={title || undefined}
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Colors follow the active theme's accent (--brand / --accent-bright). */}
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="rgb(var(--accent-bright))" />
          <stop offset="0.55" stopColor="rgb(var(--brand))" />
          <stop offset="1" stopColor="rgb(var(--brand-deep))" />
        </linearGradient>
      </defs>
      {/* tilted orbit ring */}
      <ellipse
        cx="50" cy="50" rx="44" ry="19" fill="none"
        stroke="rgb(var(--brand))" strokeWidth="3" opacity="0.45"
        transform="rotate(-28 50 50)"
      />
      {/* main four-point spark (concave diamond) */}
      <path
        d="M 50 12 C 53.5 38 62 46.5 88 50 C 62 53.5 53.5 62 50 88 C 46.5 62 38 53.5 12 50 C 38 46.5 46.5 38 50 12 Z"
        fill={`url(#${gid})`}
      />
      {/* accent mini-spark */}
      <path
        d="M 78 18 C 79 25.5 81 27.5 88.5 28.5 C 81 29.5 79 31.5 78 39 C 77 31.5 75 29.5 67.5 28.5 C 75 27.5 77 25.5 78 18 Z"
        fill="rgb(var(--accent-bright))"
      />
    </svg>
  );
}
