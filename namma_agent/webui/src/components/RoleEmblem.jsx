// Phase 9 W4: an emblem per Roman role, drawn here as original line art in the
// current text colour (so it follows every theme):
//   Imperator   (agent mode)      a laurel wreath
//   Scriba      (chat mode)       a wax tablet and stylus
//   Architectus (setup mode)      a pair of dividers
//   Legatus     (sub-agents)      a military standard (vexillum)
const PATHS = {
  imperator: (
    <>
      <path d="M12 20c-4.2-1.4-7-5.3-7-9.6 0-1.6.4-3.1 1-4.4M12 20c4.2-1.4 7-5.3 7-9.6 0-1.6-.4-3.1-1-4.4" />
      {[[6.3, 15], [5.2, 11.5], [5.6, 8], [7, 5.2]].map(([x, y], i) => (
        <ellipse key={`l${i}`} cx={x} cy={y} rx="1" ry="2" transform={`rotate(${-40 + i * 12} ${x} ${y})`} />
      ))}
      {[[17.7, 15], [18.8, 11.5], [18.4, 8], [17, 5.2]].map(([x, y], i) => (
        <ellipse key={`r${i}`} cx={x} cy={y} rx="1" ry="2" transform={`rotate(${40 - i * 12} ${x} ${y})`} />
      ))}
      <path d="M10 20.5l2-1 2 1" />
    </>
  ),
  scriba: (
    <>
      <rect x="4.5" y="5" width="11" height="14" rx="1.5" />
      <path d="M7 9h6M7 12h6M7 15h4" />
      <path d="M19.5 4.5l-4 11.5-1 2.2.2-2.4 4-11.4z" />
    </>
  ),
  architectus: (
    <>
      <circle cx="12" cy="4.6" r="1.4" />
      <path d="M11.3 6l-4.3 13.5M12.7 6l4.3 13.5" />
      <path d="M8.2 15.5c2.4 1.2 5.2 1.2 7.6 0" />
    </>
  ),
  legatus: (
    <>
      <path d="M12 3v18" />
      <path d="M8 6.5h8" />
      <path d="M8.5 6.5v7.5l3.5-1.6 3.5 1.6V6.5" />
      <circle cx="12" cy="3" r="1" />
    </>
  ),
};

export default function RoleEmblem({ role = "imperator", size = 16, className = "" }) {
  const key = String(role).toLowerCase();
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" data-emblem={key}
         fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
         className={className}>
      {PATHS[key] || PATHS.imperator}
    </svg>
  );
}
