// Settings → McpTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { McpAddPanel, StateBadge, removeServer } from "../SetupUI.jsx";
import { saveMcpServers, fetchMcp, reloadMcp, toggleMcpServer, toggleTool } from "../../api.js";
import { Section, Chevron, CollapsibleSection, _box, _btn, _btnGhost } from "./shared.jsx";

// The "MCP → Config" tab: edit the Model Context Protocol server config as JSON.
// What you write here is the `mcp` block of the config (servers + their launch
// commands), saved into user_config.yaml and applied live by reconnecting — no
// restart. Each server's tools then appear in the Servers tab (and the Toolsets
// tab) as mcp_<server>_<tool>.
export const MCP_CONFIG_PLACEHOLDER = `{
  "servers": [
    {
      "name": "filesystem",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "C:/Users/me"],
      "enabled": true
    }
  ]
}`;

export function McpConfigTab() {
  const [text, setText] = useState(null);   // JSON string being edited
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);     // {ok, text}

  useEffect(() => {
    fetchMcp().then((r) => setText(r?.config_json || '{\n  "servers": []\n}'));
  }, []);

  async function save() {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      setMsg({ ok: false, text: "Invalid JSON — " + (e?.message || "parse error") });
      return;
    }
    if (typeof parsed !== "object" || Array.isArray(parsed)) {
      setMsg({ ok: false, text: 'Top level must be an object, e.g. { "servers": [ … ] }.' });
      return;
    }
    setBusy(true); setMsg(null);
    // Validated server-side: an invalid list is refused (nothing saved); warnings
    // (a literal token, a missing ${VAR}) are shown but don't block. Servers then
    // connect in the background — the Servers tab shows each one's status.
    const r = await saveMcpServers(Array.isArray(parsed.servers) ? parsed.servers : []);
    setBusy(false);
    if (r && r.ok) {
      setText(r.config_json || text);
      const warn = (r.warnings || []).map((w) => `${w.server}: ${w.field} — ${w.message}`).join("; ");
      setMsg({ ok: true, text: `Saved — servers are connecting (see the Servers tab).${warn ? " Warnings: " + warn : ""}` });
    } else {
      const errs = (r?.errors || []).map((e) => `${e.server ? e.server + ": " : ""}${e.field ? e.field + " — " : ""}${e.message}`).join("; ");
      setMsg({ ok: false, text: `Not saved — ${errs || "the server didn't answer"}` });
    }
  }

  if (text === null) return <div className="text-fg-subtle">Loading…</div>;
  return (
    <Section title="MCP server config"
             hint="Configure external Model Context Protocol servers as JSON. Each server is launched as a local process; its tools become callable by the assistant. Saving reconnects immediately — no restart.">
      <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
                rows={16} placeholder={MCP_CONFIG_PLACEHOLDER}
                className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm font-mono leading-relaxed outline-none focus:border-brand resize-y" />
      <div className="text-xs text-fg-subtle">
        Each entry needs a <span className="font-mono">name</span> and either a <span className="font-mono">command</span> (argv array, local) or <span className="font-mono">"transport": "http"</span> + <span className="font-mono">url</span> (remote). Optional: <span className="font-mono">env</span> / <span className="font-mono">headers</span> (write secrets as <span className="font-mono">{"${NAME}"}</span> — the value comes from the vault), <span className="font-mono">cwd</span>, <span className="font-mono">enabled</span>, <span className="font-mono">connect_timeout</span>, <span className="font-mono">call_timeout</span>.
      </div>
      <div className="flex items-center gap-3 pt-0.5">
        <button onClick={save} disabled={busy} className={_btn}>{busy ? "Applying…" : "Apply & reconnect"}</button>
        {msg && (
          <span className={`text-sm ${msg.ok ? "text-success" : "text-brand-deep dark:text-amber-400"}`}>
            {msg.text}
          </span>
        )}
      </div>
    </Section>
  );
}

// The "MCP → Servers" tab: every configured MCP server, whether it connected, and
// the tools it exposes — each with an on/off switch. Toggling a tool reuses the
// same per-tool disable used by the Toolsets tab (mcp tools register as
// mcp_<server>_<tool>), so a flipped tool drops out of every turn.
export function McpServersTab() {
  const [data, setData] = useState(null);   // {servers:[...]}
  const [busy, setBusy] = useState({});     // tool name -> in-flight
  const [srvBusy, setSrvBusy] = useState({}); // server name -> in-flight (whole-server toggle)
  const [open, setOpen] = useState({});     // server name -> tools expanded
  const [reloading, setReloading] = useState(false);

  const load = () => fetchMcp().then((r) => setData(r || { servers: [] }));
  useEffect(() => { load(); }, []);
  // Servers connect in the background (Phase 5): refresh on every mcp_status push.
  useEffect(() => {
    let t = null;
    const on = () => { clearTimeout(t); t = setTimeout(load, 250); };
    window.addEventListener("namma-mcp-status", on);
    return () => { window.removeEventListener("namma-mcp-status", on); clearTimeout(t); };
  }, []);

  // Two-step remove (native confirm() is a no-op in the desktop window).
  const [confirmRm, setConfirmRm] = useState("");
  async function remove(name) {
    if (confirmRm !== name) { setConfirmRm(name); return; }
    setConfirmRm("");
    const r = await removeServer(name);
    if (r?.servers) setData(r); else if (r) load();
  }

  async function flip(server, t) {
    setBusy((b) => ({ ...b, [t.name]: true }));
    const next = !t.enabled;
    setData((d) => ({ ...d, servers: d.servers.map((s) => s.name !== server ? s
      : { ...s, tools: s.tools.map((x) => x.name === t.name ? { ...x, enabled: next } : x) }) }));
    const r = await toggleTool(t.name, next);
    if (!r?.ok)  // revert on failure
      setData((d) => ({ ...d, servers: d.servers.map((s) => s.name !== server ? s
        : { ...s, tools: s.tools.map((x) => x.name === t.name ? { ...x, enabled: t.enabled } : x) }) }));
    setBusy((b) => ({ ...b, [t.name]: false }));
  }

  // Turn an ENTIRE server on/off: persists its `enabled` flag and reconnects, so a
  // disabled server isn't launched at all (vs per-tool toggles above).
  async function flipServer(s) {
    const next = s.enabled === false;   // currently off → turn on
    setSrvBusy((b) => ({ ...b, [s.name]: true }));
    const r = await toggleMcpServer(s.name, next);
    if (r && r.servers) setData(r); else await load();
    setSrvBusy((b) => ({ ...b, [s.name]: false }));
  }

  async function reload() {
    setReloading(true);
    const r = await reloadMcp();
    if (r) setData(r);
    setReloading(false);
  }

  if (!data) return <div className="text-fg-subtle">Loading…</div>;
  const servers = data.servers || [];

  return (
    <div className="space-y-4">
      <Section title="Add MCP servers"
               hint="Pick a curated server, import one from Claude Desktop / Cursor / VS Code or a URL, or detect what this machine can run. Keys go into the vault through a secure field. Servers connect in the background.">
        <McpAddPanel onChanged={load} />
      </Section>

      <Section title="MCP servers"
               hint="Configured Model Context Protocol servers and the tools each exposes. Use the switch on a server to turn the whole server on/off; expand it to toggle individual tools. Edit the raw JSON in the Config tab. Toggling only touches that one server — but Docker-based servers can take ~30s to start.">
        <button onClick={reload} disabled={reloading} className={_btnGhost + " disabled:opacity-50 text-sm"}>
          {reloading ? "Reconnecting…" : "↻ Reconnect servers"}
        </button>
      </Section>

      {servers.length === 0 && (
        <div className="text-fg-subtle text-sm">
          No MCP servers configured yet — add one above.
        </div>
      )}

      {servers.map((s) => {
        const serverOn = s.enabled !== false;
        const isOpen = open[s.name] ?? false;
        const flipping = !!srvBusy[s.name];
        return (
        <div key={s.name} className={`${_box} ${serverOn ? "" : "opacity-70"}`}>
          {/* server header: chevron + status + name + count  ·····  whole-server switch */}
          <div className="flex items-center justify-between gap-3">
            <button type="button" onClick={() => setOpen((o) => ({ ...o, [s.name]: !isOpen }))}
                    className="flex items-center gap-2 min-w-0 text-left hover:opacity-80">
              <Chevron open={isOpen} />
              <span className="font-medium text-base truncate">{s.name}</span>
              <StateBadge state={flipping ? "connecting" : (serverOn ? s.state : "disabled")} />
              <span className="text-2xs text-fg-subtle shrink-0">
                {s.connected ? `${s.tools.length} tool${s.tools.length === 1 ? "" : "s"}` : ""}
                {s.transport === "http" ? " · remote" : ""}
              </span>
            </button>
            <button aria-label={serverOn ? "Turn server off" : "Turn server on"} role="switch" aria-checked={serverOn} type="button" disabled={flipping} title={serverOn ? "Turn server off" : "Turn server on"}
                    onClick={() => flipServer(s)}
                    className={`h-6 w-11 rounded-full transition relative shrink-0 disabled:opacity-50 ${serverOn ? "bg-brand" : "bg-border"}`}>
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${serverOn ? "left-[22px]" : "left-0.5"}`} />
            </button>
          </div>

          {isOpen && (
            <div className="mt-2.5">
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="text-2xs font-mono text-fg-subtle break-all">
                  {s.transport === "http" ? s.url : (s.command || []).join(" ")}
                </div>
                <button type="button" onClick={() => remove(s.name)}
                        className="text-xs text-danger hover:underline shrink-0">
                  {confirmRm === s.name ? "Click again to remove" : "Remove"}
                </button>
              </div>
              {!serverOn ? (
                <div className="text-xs text-fg-subtle">Server is off — turn it on to connect and load its tools.</div>
              ) : s.state === "connecting" ? (
                <div className="text-xs text-fg-subtle">
                  Connecting in the background — first runs download packages or pull images.
                </div>
              ) : !s.connected ? (
                <div className="text-xs text-danger">
                  {s.error || "Couldn't connect"} — fix it (or ask setup mode), then Reconnect.
                </div>
              ) : s.tools.length === 0 ? (
                <div className="text-xs text-fg-subtle">Server exposes no tools.</div>
              ) : (
                <div className="space-y-1.5">
                  {s.tools.map((t) => (
                    <div key={t.name} className="rounded-lg border border-border p-2.5 flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <span className="font-medium font-mono text-sm">{t.tool}</span>
                        {t.description && (
                          <div className="text-sm text-fg-subtle mt-0.5">{t.description}</div>
                        )}
                      </div>
                      <button type="button" disabled={!!busy[t.name]} onClick={() => flip(s.name, t)}
                              className={`h-6 w-11 rounded-full transition relative shrink-0 mt-0.5 disabled:opacity-50 ${t.enabled ? "bg-brand" : "bg-border"}`}>
                        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${t.enabled ? "left-[22px]" : "left-0.5"}`} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        );
      })}
    </div>
  );
}

// Settings → MCP (Phase 9 W1): the two MCP tabs merged into one. Servers come
// first (add from the catalogue, toggle, inspect tools); the raw JSON config,
// which most people never need, folds away underneath.
export function McpTab() {
  return (
    <div className="space-y-7">
      <McpServersTab />
      <CollapsibleSection title="Edit the raw config (JSON)"
                          hint="For servers the catalogue doesn't list, or bulk edits. Apply & reconnect relaunches every server.">
        <McpConfigTab />
      </CollapsibleSection>
    </div>
  );
}
