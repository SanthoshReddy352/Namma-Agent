// Settings → SecurityTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { fetchSecurityOverview, migrateSecrets } from "../../api.js";
import { CollapsibleSection, Section } from "./shared.jsx";

// ── Security tab (Phase 1e) — the whole trust model on one screen ──
export const SecChip = ({ tone = "gray", children }) => {
  const tones = {
    green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    amber: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
    red: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    gray: "bg-surface-hover text-fg-subtle",
  };
  return <span className={`inline-block px-1.5 py-0.5 rounded text-2xs font-medium ${tones[tone]}`}>{children}</span>;
};

export const SecCard = ({ children }) => (
  <div className="rounded-xl border border-border divide-y divide-border overflow-hidden">{children}</div>
);

export const SecEmpty = ({ children }) => (
  <div className="px-3.5 py-3 text-sm text-fg-subtle">{children}</div>
);

export function SecurityTab() {
  const [data, setData] = useState(null);
  const [migrating, setMigrating] = useState(false);
  const [migrateNote, setMigrateNote] = useState("");

  const refresh = () => fetchSecurityOverview().then((d) => d && d.ok && setData(d));
  useEffect(() => { refresh(); }, []);

  if (!data) return <div className="text-sm text-fg-subtle">Loading…</div>;

  const q = data.quarantine || {};
  const quarantineCount = (q.memory?.length || 0) + (q.documents?.length || 0) + (q.web?.length || 0);
  const sandbox = data.sandbox || {};
  const urlguard = data.urlguard || {};
  const shellBackend = data.shell_backend || {};
  const trustTone = { owner: "green", trusted: "amber", untrusted: "red" };

  async function migrate() {
    setMigrating(true); setMigrateNote("");
    const r = await migrateSecrets(false);
    setMigrateNote(r?.migrated?.length
      ? `Moved ${r.migrated.length} secret(s) into the ${r.backend} vault.`
      : (r?.error || "Nothing to migrate — no secret-looking entries in .env."));
    setMigrating(false);
    refresh();
  }

  const fmtTime = (iso) => (iso || "").replace("T", " ").slice(0, 16);

  return (
    <>
      <Section title="How trust works here"
               hint="Plain language, no fine print — this is the model everything below enforces.">
        <div className="text-sm leading-relaxed text-fg-soft space-y-1.5">
          <p>• Messages are trusted by <b>where they come from</b>. Your own channels run at full capability; messages from an <b>untrusted</b> channel can't run destructive tools, are marked as data (not instructions) to the AI, and can't write memory — attempts are quarantined below.</p>
          <p>• Everything the AI fetches from the web is <b>screened for prompt injection</b>; suspicious pages are delivered wrapped in a warning, never silently.</p>
          <p>• Shell commands run inside an <b>OS sandbox</b> with resource caps, and destructive tools always need your approval (declines are recorded).</p>
          <p>• Tokens and API keys live in the <b>OS vault</b>, and known secret values are masked everywhere the AI (or the log) could repeat them.</p>
          <p>• When the AI fetches a URL, it <b>can't reach into private networks</b> — your router, your NAS, or the cloud metadata service that hands out server credentials.</p>
        </div>
      </Section>

      <Section title="Per-channel trust" hint="Change levels in Settings → Messaging.">
        <SecCard>
          {Object.entries(data.trust || {}).map(([ch, lvl]) => (
            <div key={ch} className="px-3.5 py-2 flex items-center gap-3">
              <span className="text-sm capitalize text-fg">{ch}</span>
              <span className="ml-auto"><SecChip tone={trustTone[lvl] || "gray"}>{lvl}</SecChip></span>
            </div>
          ))}
        </SecCard>
      </Section>

      <Section title="Shell sandbox">
        <SecCard>
          <div className="px-3.5 py-2.5 flex items-center gap-2.5">
            <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${sandbox.active ? "bg-emerald-500" : sandbox.enabled ? "bg-amber-400" : "bg-border"}`} />
            <span className="text-sm text-fg">
              {sandbox.enabled
                ? (sandbox.active === false ? "Enabled, but the OS refused — running uncapped" : "Enabled")
                : "Disabled in config"}
            </span>
            <span className="ml-auto text-xs text-fg-subtle">
              {sandbox.mechanism === "job-object" ? "Windows Job Object" : "POSIX rlimits"}
              {sandbox.memory_mb ? ` · ${(sandbox.memory_mb / 1024).toFixed(0)} GB cap` : ""}
              {sandbox.max_processes ? ` · ${sandbox.max_processes} procs` : ""}
            </span>
          </div>
          <div className="px-3.5 py-2.5 flex items-center gap-2.5">
            <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${shellBackend.backend === "local" ? "bg-border" : shellBackend.state === "running" || shellBackend.backend === "ssh" ? "bg-emerald-500" : "bg-amber-400"}`} />
            <span className="text-sm text-fg">
              {shellBackend.backend === "docker"
                ? `Runs in a container (${shellBackend.container}${shellBackend.state ? ` · ${shellBackend.state}` : ""})`
                : shellBackend.backend === "ssh"
                  ? `Runs on ${shellBackend.host}`
                  : "Runs on this machine"}
            </span>
            <span className="ml-auto text-xs text-fg-subtle text-right">
              {shellBackend.caps || shellBackend.detail}
            </span>
          </div>
        </SecCard>
        {shellBackend.backend !== "local" && (
          <div className="text-xs text-fg-subtle leading-relaxed">
            The resource caps above bound the local {shellBackend.backend} client, not the
            work itself — {shellBackend.backend === "docker"
              ? "the container's own limits do that."
              : "the remote host's own limits do that."}
          </div>
        )}
      </Section>

      <Section title="Web fetch guard"
               hint="Stops a fetched URL reaching your private network — the confused-deputy case (an untrusted sender asking the AI to read an internal address).">
        <SecCard>
          <div className="px-3.5 py-2.5 flex items-center gap-2.5">
            <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${urlguard.enabled ? "bg-emerald-500" : "bg-amber-400"}`} />
            <span className="text-sm text-fg">
              {urlguard.enabled
                ? "Private, loopback and cloud-metadata addresses are blocked"
                : "Off — private addresses are reachable (allow_private_urls is on)"}
            </span>
            <span className="ml-auto text-xs text-fg-subtle">
              {(urlguard.schemes || []).join("/") || "http/https"} only · redirects checked
            </span>
          </div>
        </SecCard>
      </Section>

      {((data.extensions?.hooks?.count || 0) > 0
        || (data.extensions?.user_tools || []).length > 0
        || (data.extensions?.hooks?.errors || []).length > 0) && (
        <Section title="Your extensions"
                 hint="Code you added yourself, running in-process with the assistant. Listed here because it should never be invisible — even though you put it there.">
          <SecCard>
            {(data.extensions?.user_tools || []).map((n) => (
              <div key={n} className="px-3.5 py-2 flex items-center gap-3">
                <span className="text-sm font-mono text-fg">{n}</span>
                <span className="ml-auto"><SecChip tone="amber">custom tool</SecChip></span>
              </div>
            ))}
            {(data.extensions?.hooks?.hooks || []).map((h) => (
              <div key={h.name} className="px-3.5 py-2 flex items-center gap-3">
                <span className="text-sm font-mono text-fg">{h.name}</span>
                <span className="text-xs text-fg-subtle">{h.events.join(", ")}</span>
                <span className="ml-auto"><SecChip tone="amber">hook</SecChip></span>
              </div>
            ))}
            {(data.extensions?.hooks?.errors || []).map((e) => (
              <div key={e.name} className="px-3.5 py-2 flex items-center gap-3">
                <span className="text-sm font-mono text-fg">{e.name}</span>
                <span className="text-xs text-warning truncate">{e.error}</span>
                <span className="ml-auto"><SecChip tone="red">failed to load</SecChip></span>
              </div>
            ))}
          </SecCard>
        </Section>
      )}

      <Section title="Secrets vault"
               hint="Names only — values never leave the OS store. Known secret values are masked in tool output and logs.">
        <SecCard>
          <div className="px-3.5 py-2 flex items-center gap-3">
            <span className="text-sm text-fg">Backend</span>
            <span className="ml-auto"><SecChip tone="green">{data.secrets?.backend}</SecChip></span>
          </div>
          {(data.secrets?.names || []).map((n) => (
            <div key={n} className="px-3.5 py-2 text-sm font-mono text-fg-soft">{n}</div>
          ))}
          {!(data.secrets?.names || []).length && <SecEmpty>The vault is empty.</SecEmpty>}
        </SecCard>
        <div className="flex items-center gap-3">
          <button onClick={migrate} disabled={migrating}
                  className="px-3 py-1.5 rounded-lg border border-border hover:bg-surface-hover disabled:opacity-40 text-sm">
            {migrating ? "Moving…" : "Move .env tokens into the vault"}
          </button>
          {migrateNote && <span className="text-xs text-fg-subtle">{migrateNote}</span>}
        </div>
      </Section>

      <Section title={`Quarantine log${quarantineCount ? ` (${quarantineCount})` : ""}`}
               hint="Content that was caught and held: memory writes from unverified senders, injection-flagged documents, and suspicious web pages.">
        <SecCard>
          {(q.memory || []).map((m) => (
            <div key={m.id} className="px-3.5 py-2.5 space-y-1">
              <div className="flex items-center gap-2">
                <SecChip tone={m.status === "untrusted" ? "red" : "amber"}>
                  {m.status === "untrusted" ? "untrusted sender" : "injection-flagged"}
                </SecChip>
                <span className="text-xs text-fg-subtle">memory · {fmtTime(m.at)}</span>
              </div>
              <div className="text-sm text-fg-soft">{m.text}</div>
            </div>
          ))}
          {(q.documents || []).map((d) => (
            <div key={d.id} className="px-3.5 py-2.5 space-y-1">
              <div className="flex items-center gap-2">
                <SecChip tone="amber">flagged document</SecChip>
                <span className="text-xs text-fg-subtle">
                  {d.project ? `project “${d.project}” · ` : ""}{fmtTime(d.at)}
                </span>
              </div>
              <div className="text-sm text-fg-soft">{d.name}</div>
              {(d.reasons || []).length > 0 &&
                <div className="text-xs text-fg-subtle">{d.reasons.join(" · ")}</div>}
            </div>
          ))}
          {(q.web || []).map((w, i) => (
            <div key={i} className="px-3.5 py-2.5 space-y-1">
              <div className="flex items-center gap-2">
                <SecChip tone="amber">suspicious web page</SecChip>
                <span className="text-xs text-fg-subtle">{w.tool} · {fmtTime(w.at)}</span>
              </div>
              <div className="text-sm text-fg-soft">{w.summary}</div>
            </div>
          ))}
          {!quarantineCount && <SecEmpty>Nothing in quarantine — no attacks caught yet.</SecEmpty>}
        </SecCard>
      </Section>

      <CollapsibleSection
        title={`Recent tool activity (audit trail)${data.audit?.length ? ` — ${data.audit.length}` : ""}`}
        hint="The newest 50 tool runs, including destructive actions you approved or declined.">
        <SecCard>
          {(data.audit || []).slice(0, 50).map((a) => (
            <div key={a.id} className="px-3.5 py-2 flex items-center gap-2.5">
              <span className={`h-2 w-2 rounded-full shrink-0 ${a.ok ? "bg-emerald-500" : "bg-red-400"}`} />
              <span className="text-sm font-mono text-fg">{a.tool}</span>
              {a.destructive && <SecChip tone={a.ok ? "amber" : "red"}>{a.ok ? "approved" : "declined"}</SecChip>}
              <span className="ml-auto text-xs text-fg-subtle shrink-0">{fmtTime(a.at)}</span>
            </div>
          ))}
          {!(data.audit || []).length && <SecEmpty>No tool activity recorded yet.</SecEmpty>}
        </SecCard>
      </CollapsibleSection>
    </>
  );
}
