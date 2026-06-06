function Dot({ state }) {
  const color =
    state === "running" ? "bg-accent animate-pulse" : state === "ok" ? "bg-emerald-400" : state === "fail" ? "bg-red-400" : "bg-glow";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export default function Timeline({ items }) {
  if (!items.length) return null;
  return (
    <div className="glass rounded-2xl px-4 py-3 animate-rise">
      <div className="text-[11px] uppercase tracking-wider text-ink-50/40 mb-2">activity</div>
      <ul className="space-y-1.5">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm">
            {it.kind === "preamble" ? (
              <>
                <span className="mt-1.5 inline-block h-2 w-2 rounded-full bg-glow-soft" />
                <span className="italic text-ink-50/80">“{it.text}”</span>
              </>
            ) : (
              <>
                <span className="mt-1.5"><Dot state={it.state} /></span>
                <span className="font-mono text-[13px] text-ink-50/90">
                  {it.tool}
                  {it.summary && <span className="ml-2 text-ink-50/50">— {it.summary}</span>}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
