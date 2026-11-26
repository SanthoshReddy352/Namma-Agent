// Settings → PacksTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { exportPack, fetchPackItems, inspectPack, installPack, packDownloadUrl } from "../../api.js";
import { Section, Toggle, _box, _btn } from "./shared.jsx";

export function PacksTab() {
  const [items, setItems] = useState(null);                 // {skills:[], tools:[]}
  const [pick, setPick] = useState({ skills: {}, tools: {} }); // name/file -> bool
  const [busy, setBusy] = useState(false);
  const [exported, setExported] = useState(null);           // {filename, path}

  // import state
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);             // inspect result or {error}
  const [approve, setApprove] = useState({});               // tool name -> bool (default off)
  const [openSrc, setOpenSrc] = useState({});               // tool name -> expanded
  const [overwrite, setOverwrite] = useState(false);
  const [result, setResult] = useState(null);               // install summary

  useEffect(() => {
    fetchPackItems().then((r) => {
      const it = { skills: r?.skills || [], tools: r?.tools || [] };
      setItems(it);
      setPick({
        skills: Object.fromEntries(it.skills.map((s) => [s.name, true])),
        tools: Object.fromEntries(it.tools.map((t) => [t.file, true])),
      });
    });
  }, []);

  const toggle = (kind, key) => setPick((p) => ({ ...p, [kind]: { ...p[kind], [key]: !p[kind][key] } }));
  const selected = (kind) => Object.entries(pick[kind] || {}).filter(([, v]) => v).map(([k]) => k);

  async function doExport() {
    setBusy(true); setExported(null);
    const r = await exportPack(selected("skills"), selected("tools"));
    setBusy(false);
    if (r?.ok) setExported(r);
  }

  async function onPick(f) {
    setFile(f); setPreview(null); setResult(null); setApprove({}); setOpenSrc({});
    if (!f) return;
    setBusy(true);
    const r = await inspectPack(f);
    setBusy(false);
    setPreview(r || { error: "could not read file" });
  }

  async function doInstall() {
    setBusy(true); setResult(null);
    const approvedTools = (preview?.tools || []).filter((t) => approve[t.name]).map((t) => t.name);
    const skills = (preview?.skills || []).map((s) => s.name);
    const r = await installPack(file, { approvedTools, skills, overwrite });
    setBusy(false);
    setResult(r?.summary || (r?.error ? { error: r.error } : { error: "install failed" }));
    fetchPackItems().then((x) => setItems({ skills: x?.skills || [], tools: x?.tools || [] }));
  }

  if (!items) return <div className="text-ink-faint">Loading…</div>;
  const nSel = selected("skills").length + selected("tools").length;

  return (
    <div className="space-y-5">
      {/* ── Export ── */}
      <Section title="Export a pack"
               hint="Bundle your assistant-created skills and tools into one shareable .zip. Pick what to include; the file carries its own install instructions.">
        {items.skills.length === 0 && items.tools.length === 0 ? (
          <div className="text-fg-subtle text-sm">
            You haven't created any skills or tools yet. Ask the assistant to make one, then come back here to share it.
          </div>
        ) : (
          <>
            {items.skills.length > 0 && (
              <div className={_box}>
                <div className="text-xs text-fg-subtle mb-2">Skills</div>
                <div className="space-y-1.5">
                  {items.skills.map((s) => (
                    <label key={s.name} className="flex items-start gap-2 cursor-pointer">
                      <input type="checkbox" checked={!!pick.skills[s.name]} onChange={() => toggle("skills", s.name)} className="mt-1" />
                      <span><span className="font-medium">{s.name}</span>
                        {s.description && <span className="text-fg-subtle"> — {s.description}</span>}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            {items.tools.length > 0 && (
              <div className={_box}>
                <div className="text-xs text-fg-subtle mb-2">Tools <span className="opacity-70">(Python)</span></div>
                <div className="space-y-1.5">
                  {items.tools.map((t) => (
                    <label key={t.file} className="flex items-start gap-2 cursor-pointer">
                      <input type="checkbox" checked={!!pick.tools[t.file]} onChange={() => toggle("tools", t.file)} className="mt-1" />
                      <span><span className="font-medium">{t.name}</span>
                        {t.description && <span className="text-fg-subtle"> — {t.description}</span>}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="flex items-center gap-3">
              <button onClick={doExport} disabled={busy || nSel === 0} className={_btn}>
                {busy ? "Building…" : `Export ${nSel} item${nSel === 1 ? "" : "s"}`}
              </button>
              {exported && (
                <span className="text-sm text-brand-deep dark:text-emerald-400">
                  Saved. <a href={packDownloadUrl(exported.filename)} download className="underline">Download {exported.filename}</a>
                  <span className="block text-fg-subtle text-xs">{exported.path}</span>
                </span>
              )}
            </div>
          </>
        )}
      </Section>

      <div className="border-t border-border" />

      {/* ── Import ── */}
      <Section title="Import a pack"
               hint="Open a .zip someone shared with you. Skills install directly; tools run code on your machine, so review and approve each one.">
        <input type="file" accept=".zip,application/zip" onChange={(e) => onPick(e.target.files?.[0] || null)}
               className="block text-sm text-fg-muted" />

        {preview?.error && <div className="text-red-500 text-sm">Couldn't read this pack: {preview.error}</div>}

        {preview && !preview.error && (
          <div className="space-y-3">
            {preview.created_by && (
              <div className="text-xs text-fg-subtle">
                From <span className="font-medium">{preview.created_by}</span>{preview.created ? ` · ${preview.created}` : ""}
              </div>
            )}

            {preview.skills?.length > 0 && (
              <div className={_box}>
                <div className="text-xs text-fg-subtle mb-2">Skills (install directly)</div>
                <div className="space-y-1">
                  {preview.skills.map((s) => (
                    <div key={s.name} className="text-sm">
                      <span className="font-medium">{s.name}</span>
                      {s.description && <span className="text-fg-subtle"> — {s.description}</span>}
                      {s.exists && <span className="ml-2 text-warning text-xs">already installed</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {preview.tools?.length > 0 && (
              <div className={_box}>
                <div className="text-xs text-warning mb-2">
                  ⚠️ Tools run Python in-process. Only approve tools from a source you trust — review the source first.
                </div>
                <div className="space-y-2">
                  {preview.tools.map((t) => (
                    <div key={t.name} className="rounded-lg border border-border p-2">
                      <label className="flex items-start gap-2 cursor-pointer">
                        <input type="checkbox" checked={!!approve[t.name]}
                               onChange={() => setApprove((a) => ({ ...a, [t.name]: !a[t.name] }))} className="mt-1" />
                        <span className="flex-1">
                          <span className="font-medium">{t.name}</span>
                          {t.description && <span className="text-fg-subtle"> — {t.description}</span>}
                          {t.exists && <span className="ml-2 text-warning text-xs">already installed</span>}
                        </span>
                        <button type="button" onClick={(e) => { e.preventDefault(); setOpenSrc((o) => ({ ...o, [t.name]: !o[t.name] })); }}
                                className="text-xs underline text-fg-subtle shrink-0">
                          {openSrc[t.name] ? "hide source" : "view source"}
                        </button>
                      </label>
                      {openSrc[t.name] && (
                        <pre className="mt-2 max-h-64 overflow-auto rounded bg-surface-sunken text-xs p-2 whitespace-pre-wrap">{t.source || "(source unavailable)"}</pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {(preview.skills?.some((s) => s.exists) || preview.tools?.some((t) => t.exists)) && (
              <Toggle label="Overwrite items that already exist" checked={overwrite} onChange={setOverwrite} />
            )}

            <button onClick={doInstall} disabled={busy} className={_btn}>
              {busy ? "Installing…" : "Install"}
            </button>
          </div>
        )}

        {result && (result.error ? (
          <div className="text-red-500 text-sm">{result.error}</div>
        ) : (
          <div className="text-sm space-y-1">
            <div className="text-brand-deep dark:text-emerald-400">Installed.</div>
            <PackResultLine label="Skills" r={result.skills} />
            <PackResultLine label="Tools" r={result.tools} />
          </div>
        ))}
      </Section>
    </div>
  );
}

export const PackResultLine = ({ label, r }) => {
  if (!r) return null;
  const parts = [];
  if (r.installed?.length) parts.push(`${r.installed.length} installed`);
  if (r.skipped?.length) parts.push(`${r.skipped.length} skipped`);
  if (r.failed?.length) parts.push(`${r.failed.length} failed`);
  return <div className="text-fg-muted">{label}: {parts.join(", ") || "none"}</div>;
};
