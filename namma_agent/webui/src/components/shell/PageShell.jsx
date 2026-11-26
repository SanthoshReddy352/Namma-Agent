// Phase 9: the shared layout for the gallery pages (Projects, Learning Room).
// The page's name already sits in the titlebar band, so the page opens with a
// header block instead of a second title bar: an icon tile, the title, a
// one-line purpose, the primary action, and optional stats. Content sits in a
// centred column on translucent surfaces over the painted paper.
export default function PageShell({ icon: Icon, title, description, action, stats, children }) {
  return (
    <main className="chat-legible flex-1 overflow-y-auto px-6 md:px-10 py-8">
      <div className="max-w-5xl mx-auto">
        <header className="flex flex-wrap items-start gap-4 mb-7">
          {Icon && (
            <span className="h-12 w-12 shrink-0 grid place-items-center rounded-2xl bg-accent-wash text-accent border border-accent/20 shadow-soft">
              <Icon size={24} stroke={1.6} aria-hidden="true" />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <h1 className="font-serif text-xl font-semibold tracking-tight text-fg">{title}</h1>
            {description && <p className="mt-1 text-base text-fg-muted max-w-2xl">{description}</p>}
            {stats?.length > 0 && (
              <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
                {stats.map((s) => (
                  <div key={s.label} className="flex items-baseline gap-1.5">
                    <dt className="sr-only">{s.label}</dt>
                    <dd className="font-semibold text-fg tabular-nums">{s.value}</dd>
                    <span aria-hidden="true" className="text-fg-subtle">{s.label}</span>
                  </div>
                ))}
              </dl>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
        {children}
      </div>
    </main>
  );
}

// A primary action button for page headers.
export function PageAction({ icon: Icon, children, ...props }) {
  return (
    <button type="button" {...props}
            className="inline-flex items-center gap-2 h-10 px-4 rounded-xl bg-accent text-accent-fg text-base font-medium shadow-soft hover:opacity-90 transition">
      {Icon && <Icon size={17} stroke={1.9} aria-hidden="true" />}{children}
    </button>
  );
}

// A gallery card surface: translucent over the painted paper, lifts on hover.
export const cardClass =
  "rounded-2xl border border-border/80 bg-surface-raised/80 backdrop-blur-md shadow-soft transition hover:-translate-y-0.5 hover:shadow-pop hover:border-accent/40";

// Stable accent tone per item (chart tokens), for card strips and tiles.
const TONES = ["--chart-1", "--chart-2", "--chart-3", "--chart-5", "--chart-6", "--chart-7", "--chart-8"];
export function toneFor(id = "") {
  let h = 0;
  for (const ch of String(id)) h = (h * 33 + ch.charCodeAt(0)) >>> 0;
  return TONES[h % TONES.length];
}

export function timeAgo(iso) {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return new Date(t).toLocaleDateString();
}
