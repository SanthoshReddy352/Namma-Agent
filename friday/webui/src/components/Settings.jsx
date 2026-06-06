export default function Settings({ config, onClose }) {
  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-black/50" onClick={onClose}>
      <div className="glass rounded-2xl p-6 w-[440px] max-w-[90vw] animate-rise" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Settings</h2>
          <button onClick={onClose} className="text-ink-50/50 hover:text-ink-50">✕</button>
        </div>
        {!config ? (
          <p className="text-ink-50/50 text-sm">Backend not reachable.</p>
        ) : (
          <div className="space-y-4 text-sm">
            <Row label="Provider" value={(config.provider || []).join(" → ")} />
            <Row label="Model" value={config.model || "—"} />
            <Row label="Persona" value={config.persona} />
            <div>
              <div className="text-ink-50/40 mb-1.5">Tools ({(config.tools || []).length})</div>
              <div className="flex flex-wrap gap-1.5 max-h-40 overflow-auto">
                {(config.tools || []).map((t) => (
                  <span key={t} className="font-mono text-[11px] px-2 py-1 rounded-md bg-ink-700 text-glow-soft/80">{t}</span>
                ))}
              </div>
            </div>
            <p className="text-[11px] text-ink-50/30 pt-2">
              Provider + model are set in <span className="font-mono">friday/config.yaml</span>; keys live in <span className="font-mono">.env</span>.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-ink-50/40">{label}</span>
      <span className="font-mono text-glow-soft/90 text-right">{value}</span>
    </div>
  );
}
