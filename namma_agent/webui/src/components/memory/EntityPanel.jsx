import { useCallback, useEffect, useMemo, useState } from "react";
import { IconArrowLeft, IconArrowRight, IconArrowsLeftRight, IconGitMerge, IconPencil, IconX } from "@tabler/icons-react";
import IconButton from "../ui/IconButton.jsx";
import Button from "../ui/Button.jsx";
import { memoryGraphEntity, memoryGraphMerge, memoryGraphUpdateEntity } from "../../api.js";
import { relLabel, relTime, searchNodes, TYPE_ORDER } from "./graphModel.js";
import { TypeChip } from "./SchemaView.jsx";

// Phase 10 — one entity in focus: what it is (type, aliases, attributes), how
// it relates (live relations, and superseded ones struck through with what
// replaced them), and the FACTS behind every edge. Rename / retype / merge
// fix what resolution got wrong; merges are remembered across rebuilds.

const field = "w-full rounded-md px-2.5 h-8 bg-surface-sunken border border-border outline-none focus:border-accent text-sm text-fg";

export default function EntityPanel({ entityId, nodes = [], onClose, onPick, onChanged }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [merging, setMerging] = useState(false);
  const [mergeQ, setMergeQ] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    const r = await memoryGraphEntity(entityId);
    if (r?.ok) { setData(r); setName(r.entity.name); setType(r.entity.type); }
    else { setData(null); setErr(r?.error || "Couldn't load this entity."); }
  }, [entityId]);
  useEffect(() => { setEditing(false); setMerging(false); setMergeQ(""); load(); }, [load]);

  const live = useMemo(() => (data?.edges || []).filter((e) => !e.expired_at), [data]);
  const past = useMemo(() => (data?.edges || []).filter((e) => e.expired_at), [data]);
  const mergeHits = useMemo(
    () => searchNodes(nodes.filter((n) => n.id !== entityId), mergeQ).slice(0, 6), [nodes, entityId, mergeQ]);

  async function saveEdit() {
    setBusy(true);
    const body = {};
    if (name.trim() && name.trim() !== data.entity.name) body.name = name.trim();
    if (type && type !== data.entity.type) body.type = type;
    const r = Object.keys(body).length ? await memoryGraphUpdateEntity(entityId, body) : { ok: true };
    setBusy(false);
    if (r?.ok) { setEditing(false); await load(); onChanged?.(); } else setErr(r?.error || "Couldn't save.");
  }

  async function mergeInto(target) {
    setBusy(true);
    const r = await memoryGraphMerge(entityId, target.id);
    setBusy(false);
    if (r?.ok) { onChanged?.(); onPick?.(target.id); } else setErr(r?.error || "Couldn't merge.");
  }

  const ent = data?.entity;
  return (
    <aside className="h-full flex flex-col min-h-0 bg-surface/90 backdrop-blur" aria-label="Entity details" data-testid="entity-panel">
      <div className="flex items-start gap-2 px-4 pt-3 pb-2 border-b border-border">
        <div className="min-w-0 flex-1">
          {ent ? (
            <>
              <div className="text-md font-semibold text-fg truncate" title={ent.name}>{ent.name}</div>
              <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                <TypeChip type={ent.type} />
                {ent.is_self && <span className="text-2xs px-1.5 h-5 inline-flex items-center rounded-full bg-accent-wash text-accent">you</span>}
                {data.rank && <span className="text-2xs text-fg-subtle">rank score {Math.round(data.rank.score * 100)}</span>}
              </div>
            </>
          ) : <div className="text-sm text-fg-subtle">{err || "Loading…"}</div>}
        </div>
        {ent && !ent.is_self && (
          <IconButton label="Edit name or type" onClick={() => setEditing((v) => !v)} aria-pressed={editing}>
            <IconPencil size={16} stroke={1.7} />
          </IconButton>
        )}
        <IconButton label="Close details" onClick={onClose}><IconX size={16} stroke={1.7} /></IconButton>
      </div>

      {ent && (
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4 text-sm">
          {err && <div className="text-warning text-sm">{err}</div>}
          {editing && (
            <div className="rounded-lg border border-border p-2.5 space-y-2">
              <label className="block text-2xs uppercase tracking-wider text-fg-subtle">Name
                <input className={`${field} mt-1`} value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label className="block text-2xs uppercase tracking-wider text-fg-subtle">Type
                <select className={`${field} mt-1 capitalize`} value={type} onChange={(e) => setType(e.target.value)}>
                  {[...new Set([...TYPE_ORDER, ent.type])].map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <div className="flex gap-2 justify-end">
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                <Button size="sm" variant="primary" disabled={busy} onClick={saveEdit}>Save</Button>
              </div>
            </div>
          )}

          {(ent.aliases?.length > 0) && (
            <section>
              <h4 className="text-2xs uppercase tracking-wider text-fg-subtle mb-1">Also known as</h4>
              <div className="flex flex-wrap gap-1">
                {ent.aliases.map((a) => <span key={a} className="px-2 h-6 inline-flex items-center rounded-full bg-surface-sunken text-fg-muted text-xs">{a}</span>)}
              </div>
            </section>
          )}

          {Object.keys(ent.attributes || {}).length > 0 && (
            <section>
              <h4 className="text-2xs uppercase tracking-wider text-fg-subtle mb-1">Attributes</h4>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                {Object.entries(ent.attributes).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-fg-subtle">{relLabel(k)}</dt>
                    <dd className="text-fg break-words">{v}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}

          <section>
            <h4 className="text-2xs uppercase tracking-wider text-fg-subtle mb-1">Relations ({live.length})</h4>
            {live.length === 0 && <div className="text-fg-subtle">None live.</div>}
            <ul className="space-y-1">
              {live.map((e) => <RelationRow key={e.id} e={e} onPick={onPick} />)}
            </ul>
          </section>

          {past.length > 0 && (
            <section>
              <h4 className="text-2xs uppercase tracking-wider text-fg-subtle mb-1">History — superseded</h4>
              <ul className="space-y-1">
                {past.map((e) => <RelationRow key={e.id} e={e} onPick={onPick} superseded />)}
              </ul>
            </section>
          )}

          <section>
            <h4 className="text-2xs uppercase tracking-wider text-fg-subtle mb-1">Source facts ({data.facts.length})</h4>
            <ul className="space-y-1.5">
              {data.facts.map((f) => (
                <li key={f.id} className={`rounded-md border border-border px-2.5 py-1.5 ${f.expired || f.archived ? "opacity-60" : ""}`}>
                  <div className={`leading-snug text-fg ${f.expired ? "line-through decoration-fg-subtle" : ""}`}>{f.text}</div>
                  <div className="mt-0.5 flex flex-wrap gap-x-2 text-2xs text-fg-subtle">
                    <span>{f.kind || "fact"}</span>
                    {f.created_at && <span>{relTime(f.created_at)}</span>}
                    {f.frequency > 1 && <span>said ×{f.frequency}</span>}
                    {f.mention && <span>mentions it</span>}
                    {f.expired && <span className="text-warning">superseded</span>}
                    {f.archived && !f.expired && <span>archived</span>}
                  </div>
                </li>
              ))}
              {!data.facts.length && <li className="text-fg-subtle">No facts reference it.</li>}
            </ul>
          </section>

          {!ent.is_self && (
            <section className="pt-1">
              {!merging ? (
                <Button size="sm" variant="secondary" onClick={() => setMerging(true)}>
                  <IconGitMerge size={15} stroke={1.7} /> Same as another entity…
                </Button>
              ) : (
                <div className="rounded-lg border border-border p-2.5 space-y-2">
                  <div className="text-xs text-fg-muted">Merge <b className="text-fg">{ent.name}</b> into:</div>
                  <input className={field} autoFocus placeholder="Search entities…" value={mergeQ}
                         onChange={(e) => setMergeQ(e.target.value)} />
                  <ul className="space-y-0.5">
                    {mergeHits.map((n) => (
                      <li key={n.id}>
                        <button type="button" disabled={busy} onClick={() => mergeInto(n)}
                                className="w-full flex items-center gap-2 px-2 h-8 rounded-md hover:bg-surface-hover text-left">
                          <TypeChip type={n.type} /><span className="truncate text-fg">{n.label}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <div className="flex justify-end">
                    <Button size="sm" variant="ghost" onClick={() => { setMerging(false); setMergeQ(""); }}>Cancel</Button>
                  </div>
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </aside>
  );
}

function RelationRow({ e, onPick, superseded = false }) {
  const Arrow = !e.symmetric ? (e.direction === "out" ? IconArrowRight : IconArrowLeft) : IconArrowsLeftRight;
  return (
    <li className={`flex items-center gap-1.5 min-w-0 ${superseded ? "opacity-70" : ""}`}>
      <Arrow size={13} stroke={1.8} className="text-fg-subtle shrink-0"
             aria-label={e.symmetric ? "mutual" : e.direction === "out" ? "outgoing" : "incoming"} />
      <span className={`text-accent shrink-0 ${superseded ? "line-through" : ""}`}>{relLabel(e.rel)}</span>
      <button type="button" onClick={() => e.other?.id && onPick?.(e.other.id)}
              className={`truncate text-fg hover:underline text-left ${superseded ? "line-through" : ""}`}>
        {e.other?.name || "?"}
      </button>
      {e.support > 1 && <span className="text-2xs text-fg-subtle shrink-0" title="facts asserting it">×{e.support}</span>}
      {superseded && <span className="ml-auto text-2xs text-warning shrink-0">superseded {relTime(e.expired_at)}</span>}
      {!superseded && e.confidence != null && (
        <span className="ml-auto text-2xs text-fg-subtle shrink-0 tabular-nums" title="confidence">{Math.round(e.confidence * 100)}%</span>
      )}
    </li>
  );
}
