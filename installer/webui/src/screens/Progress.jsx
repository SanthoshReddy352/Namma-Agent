import React, { useEffect, useRef, useState } from "react";
import Stepper from "../components/Stepper.jsx";
import { Spark } from "../components/Logo.jsx";

export default function Progress({ steps, log, error, onRetry, onCancel }) {
  const [showDetails, setShowDetails] = useState(false);
  const logRef = useRef(null);

  const total = steps.length;
  const done = steps.filter((s) => s.status === "done").length;
  const active = steps.find((s) => s.status === "active");
  const current = error
    ? "Something went wrong"
    : active
    ? active.label
    : done === total && total > 0
    ? "Finishing up"
    : "Preparing…";
  const pct = total ? Math.round((done / total) * 100) : 0;

  useEffect(() => {
    if (showDetails && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log, showDetails]);

  return (
    <div className="flex h-full flex-col px-10 py-8 animate-fade">
      {/* header */}
      <div className="flex items-center gap-3">
        {!error && <Spark size={22} className="text-brand" />}
        <h2 className="text-[20px] font-semibold text-ink">{current}</h2>
        <span className="ml-auto text-[14px] font-medium text-ink-faint">
          {done} of {total} steps
        </span>
      </div>

      {/* progress bar */}
      <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-canvas-sink">
        <div
          className={"h-full rounded-full transition-all duration-500 " + (error ? "bg-bad" : "bg-brand")}
          style={{ width: `${error ? 100 : Math.max(pct, 4)}%` }}
        />
      </div>

      {/* steps */}
      <div className="mt-6 flex-1 overflow-y-auto scroll-thin">
        <Stepper steps={steps} />
        {error && (
          <div className="mt-4 rounded-xl border border-bad/30 bg-bad-soft px-4 py-3 text-[14px] text-bad">
            {error}
          </div>
        )}
      </div>

      {/* details drawer */}
      {showDetails && (
        <pre
          ref={logRef}
          className="mt-3 max-h-44 overflow-y-auto scroll-thin rounded-xl bg-[#11151d] p-4 font-mono text-[12px] leading-relaxed text-[#cdd6e6]"
        >
          {log.length ? log.join("\n") : "Waiting for output…"}
        </pre>
      )}

      {/* footer */}
      <div className="mt-5 flex items-center">
        <button className="text-[13px] font-medium text-ink-soft hover:text-ink" onClick={() => setShowDetails((v) => !v)}>
          {showDetails ? "Hide details" : "Show details"} ›
        </button>
        <div className="ml-auto flex gap-2">
          {error && (
            <button className="btn-primary px-6 py-2.5 text-[14px]" onClick={onRetry}>
              Try again
            </button>
          )}
          <button className="btn-ghost px-5 py-2.5 text-[14px]" onClick={onCancel}>
            {error ? "Close" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
