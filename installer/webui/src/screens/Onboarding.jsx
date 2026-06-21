import React, { useState } from "react";
import { Spark } from "../components/Logo.jsx";

export default function Onboarding({ fields, onFinish, busy }) {
  const [values, setValues] = useState({});
  const set = (k, v) => setValues((s) => ({ ...s, [k]: v }));

  return (
    <div className="mx-auto flex h-full w-full max-w-lg flex-col justify-center px-10 py-8 animate-rise">
      <div className="flex items-center gap-2.5">
        <Spark size={22} className="text-brand" />
        <h2 className="text-[24px] font-semibold text-ink">Tell Namma Agent about you</h2>
      </div>
      <p className="mt-1.5 text-[14px] text-ink-soft">
        Optional — so it knows you from the very first chat. Skip anything you like.
      </p>

      <div className="mt-6 space-y-4">
        {fields.map((f) => (
          <div key={f.key}>
            <label className="label">{f.label}</label>
            <input
              className="field"
              value={values[f.key] || ""}
              onChange={(e) => set(f.key, e.target.value)}
            />
          </div>
        ))}
      </div>

      <div className="mt-8 flex justify-end gap-2">
        <button className="btn-ghost px-5 py-3" onClick={() => onFinish({})} disabled={busy}>
          Skip
        </button>
        <button className="btn-primary px-7" onClick={() => onFinish(values)} disabled={busy}>
          {busy ? "Saving…" : "Finish"}
        </button>
      </div>
    </div>
  );
}
