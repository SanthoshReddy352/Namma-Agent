import { useState, useEffect, useRef, useCallback } from "react";
import { fetchSystemStatus } from "../api.js";

function colorClass(pct) {
  if (pct < 60) return "bg-emerald-500";
  if (pct < 80) return "bg-amber-500";
  return "bg-red-500";
}

function colorText(pct) {
  if (pct < 60) return "text-emerald-500";
  if (pct < 80) return "text-amber-500";
  return "text-red-500";
}

function Bar({ label, value, unit = "%" }) {
  const v = typeof value === "number" ? value : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-ink dark:text-night-ink font-medium">{label}</span>
        <span className={`tabular-nums font-semibold ${colorText(v)}`}>
          {v.toFixed(1)}{unit}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-line dark:bg-night-line overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ease-out ${colorClass(v)}`}
          style={{ width: `${Math.min(v, 100)}%` }}
        />
      </div>
    </div>
  );
}

function GaugeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M12 2a10 10 0 0 1 10 10" />
      <path d="M12 2a10 10 0 0 0-10 10" />
      <path d="M2 12h20" />
      <path d="M12 12l2.5-6" />
    </svg>
  );
}

export default function SystemMonitor() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const ref = useRef(null);
  const timerRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const snap = await fetchSystemStatus();
      setData(snap);
    } catch {
      /* swallow — widget is best-effort */
    } finally {
      setLoading(false);
    }
  }, []);

  /* auto-refresh while open */
  useEffect(() => {
    if (open) {
      refresh();
      timerRef.current = setInterval(refresh, 3000);
    }
    return () => clearInterval(timerRef.current);
  }, [open, refresh]);

  /* click-outside to close */
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const cpu = data?.cpu?.usage_percent ?? 0;
  const mem = data?.memory?.usage_percent ?? 0;
  const disk = data?.disks?.[0]?.usage_percent ?? 0;
  const topProc = data?.top_processes?.[0] ?? null;

  return (
    <div className="relative" ref={ref}>
      {/* trigger button */}
      <button
        onClick={() => setOpen((o) => !o)}
        title="System monitor — click to check CPU, RAM, disk usage"
        className="grid place-items-center h-7 w-7 rounded-lg text-ink-faint dark:text-night-faint hover:text-ink dark:hover:text-night-ink transition"
      >
        <GaugeIcon />
      </button>

      {/* popover */}
      {open && (
        <div className="absolute right-0 top-full mt-2 z-50 w-64 rounded-xl bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line shadow-lg p-3 space-y-3">
          {/* header */}
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-ink dark:text-night-ink tracking-wide uppercase">
              System
            </span>
            {loading && (
              <span className="h-1.5 w-1.5 rounded-full bg-ink-faint dark:bg-night-faint animate-pulse" />
            )}
          </div>

          {/* bars */}
          {data ? (
            <>
              <Bar label="CPU" value={cpu} />
              <Bar label="RAM" value={mem} />
              <Bar label="Disk C:\\" value={disk} />

              {topProc && (
                <div className="pt-1 border-t border-line dark:border-night-line">
                  <p className="text-[10px] text-ink-faint dark:text-night-faint truncate">
                    Top: <span className="text-ink dark:text-night-ink font-medium">{topProc.name}</span>
                    {topProc.cpu_sec != null && ` — ${(topProc.cpu_sec || 0).toFixed(1)}s CPU`}
                    {topProc.mem_mb != null && ` — ${topProc.mem_mb} MB`}
                  </p>
                </div>
              )}
            </>
          ) : (
            <div className="h-16 flex items-center justify-center">
              <span className="text-xs text-ink-faint dark:text-night-faint">Loading…</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
