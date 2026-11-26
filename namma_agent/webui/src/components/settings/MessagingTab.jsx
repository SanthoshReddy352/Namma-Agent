// Settings → MessagingTab (split out of Settings.jsx, Phase 9 W1).

import { Section, Field, Input, Select, Toggle, get } from "./shared.jsx";
import { useEffect, useState } from "react";
import { fetchCommsStatus, fetchWhatsappQR, relinkWhatsapp, setChannelTrust, startComms, stopComms } from "../../api.js";

// The gateway control shown at the top of the Messaging tab: one standalone
// inbound service that handles every configured channel. Start it to begin
// receiving/replying to messages (Telegram + Signal poll locally; Slack +
// WhatsApp need the server publicly reachable); stop it to go silent. Outbound
// notifications work regardless.
export function GatewayControl() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const refresh = () => fetchCommsStatus().then((s) => s && setStatus(s));
  useEffect(() => { refresh(); }, []);

  async function act(fn) {
    setBusy(true); setNote("");
    const s = await fn();
    if (s) { setStatus(s); if (s.error) setNote(s.error); }
    setBusy(false);
  }

  if (status && status.configured === false) {
    return (
      <Section title="Gateway" hint="The standalone service that handles all inbound messaging.">
        <div className="text-sm text-fg-subtle">Messaging is unavailable in this build.</div>
      </Section>
    );
  }

  const running = !!status?.running;
  const available = status?.available || [];
  const polling = status?.polling || [];
  const webhooks = status?.webhooks || [];

  return (
    <Section title="Gateway"
             hint="One service handles all inbound messaging across every configured channel. Start it to chat with your assistant from your messengers; stop it to go silent. (Outbound notifications always work.)">
      <div className="rounded-xl border border-border p-3 space-y-2.5">
        <div className="flex items-center gap-2.5">
          <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${running ? "bg-emerald-500" : "bg-border"}`} />
          <span className="text-base font-medium text-fg">
            {status === null ? "Checking…" : running ? "Running" : "Stopped"}
          </span>
          <div className="ml-auto flex gap-2">
            <button onClick={() => act(startComms)} disabled={busy || running}
                    className="px-3 py-1.5 rounded-lg bg-brand text-white hover:bg-brand-deep disabled:opacity-40 text-sm">
              {busy && !running ? "Starting…" : "Start"}
            </button>
            <button onClick={() => act(stopComms)} disabled={busy || !running}
                    className="px-3 py-1.5 rounded-lg border border-border hover:bg-surface-hover disabled:opacity-40 text-sm">
              {busy && running ? "Stopping…" : "Stop"}
            </button>
          </div>
        </div>
        <div className="text-xs text-fg-subtle">
          {available.length
            ? <>Configured channels: <span className="text-fg-soft">{available.join(", ")}</span></>
            : "No channels configured yet — add a token below, save, then Start."}
          {running && polling.length > 0 && <div>Polling: {polling.join(", ")}</div>}
          {running && webhooks.length > 0 && <div>Webhooks: {webhooks.join(", ")}</div>}
        </div>
        {note && <div className="text-xs text-brand-deep dark:text-amber-400">{note}</div>}
      </div>
      <div className="text-xs text-fg-subtle">
        Tip: tokens save when you leave the field. Then <b>Start</b> (or Stop &amp; Start) the gateway so it picks them up.
      </div>
      <div className="text-xs text-fg-subtle">
        Deployment &amp; gateway guides:{" "}
        <a className="text-brand hover:underline" target="_blank" rel="noreferrer"
           href="https://github.com/SanthoshReddy352/Namma-Agent/blob/main/docs/GATEWAYS.md">channel setup for servers</a>
        {" · "}
        <a className="text-brand hover:underline" target="_blank" rel="noreferrer"
           href="https://github.com/SanthoshReddy352/Namma-Agent/blob/main/docs/DEPLOY.md">self-hosting (always-on, $0 Oracle tier)</a>
        {" · "}
        <a className="text-brand hover:underline" target="_blank" rel="noreferrer"
           href="https://github.com/SanthoshReddy352/Namma-Agent/blob/main/docs/COMMS.md">per-channel credentials</a>
      </div>
    </Section>
  );
}

// Per-channel trust levels (the trust model's first visible surface). A message's
// channel decides what its sender may do: `owner` runs full turns; `untrusted`
// turns get destructive tools stripped + declined, the message wrapped in a
// data-not-instructions guard, and memory writes quarantined for review.
export const TRUST_HINTS = {
  owner: "full access — this channel is you",
  trusted: "normal turns, labeled in the audit trail",
  untrusted: "no destructive tools, guarded prompt, memory writes quarantined",
};

export function TrustControl() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState("");

  useEffect(() => { fetchCommsStatus().then((s) => s && setStatus(s)); }, []);
  if (!status || !status.trust) return null;

  const levels = status.trust_levels || ["owner", "trusted", "untrusted"];
  const channels = Object.keys(status.trust);

  async function change(channel, level) {
    setBusy(channel);
    const s = await setChannelTrust(channel, level);
    if (s && s.trust) setStatus(s);
    setBusy("");
  }

  return (
    <Section title="Trust levels"
             hint="Who can do what, per channel. Messages from an untrusted channel run with destructive tools disabled, are marked as data (not instructions) to the model, and never write long-term memory — would-be writes are quarantined for your review.">
      <div className="rounded-xl border border-border divide-y divide-border overflow-hidden">
        {channels.map((ch) => (
          <div key={ch} className="px-3.5 py-2.5 flex items-center gap-3">
            <div className="min-w-0">
              <div className="text-base text-fg capitalize">{ch}</div>
              <div className="text-xs text-fg-subtle">{TRUST_HINTS[status.trust[ch]] || ""}</div>
            </div>
            <div className={"ml-auto shrink-0 " + (busy === ch ? "opacity-50 pointer-events-none" : "")}>
              <Select value={status.trust[ch]} onChange={(v) => change(ch, v)} options={levels} />
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

// WhatsApp has two backends: the official Cloud API (Meta app, template messages,
// 24h window) or a QR-linked personal number via the WhatsApp Web protocol (link
// your own account, full two-way, no restrictions — but unofficial / against ToS).
export function WhatsAppSettings({ env, setEnv, commitEnv, data }) {
  const [serverMode, setServerMode] = useState(null);
  useEffect(() => { fetchWhatsappQR().then((r) => setServerMode(r?.mode || "cloud")); }, []);
  const mode = env.NAMMA_WHATSAPP_MODE ?? serverMode ?? "cloud";
  const setMode = (v) => { setEnv((e) => ({ ...e, NAMMA_WHATSAPP_MODE: v })); commitEnv?.("NAMMA_WHATSAPP_MODE", v); };
  const hint = mode === "qr"
    ? "Link your own number by scanning a QR (like WhatsApp Web). Full two-way, no templates — but it's an unofficial session and against WhatsApp's ToS, so use your own number at your own risk."
    : "Outbound + replies via the WhatsApp Cloud API (Meta). Official, but free-form text only inside the 24-hour window.";
  return (
    <Section title="WhatsApp" hint={hint}>
      <Field label="Backend">
        <Select value={mode} onChange={setMode} options={["cloud", "qr"]} />
      </Field>
      {mode === "cloud" ? (
        <>
          <Field label="Access token"><Input type="password" placeholder={data.env_set?.NAMMA_WHATSAPP_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_WHATSAPP_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_WHATSAPP_TOKEN: v }))} onBlur={() => commitEnv("NAMMA_WHATSAPP_TOKEN")} /></Field>
          <Field label="Phone number id"><Input placeholder={data.env_set?.NAMMA_WHATSAPP_PHONE_ID ? "(set)" : "not set"} value={env.NAMMA_WHATSAPP_PHONE_ID ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_WHATSAPP_PHONE_ID: v }))} onBlur={() => commitEnv("NAMMA_WHATSAPP_PHONE_ID")} /></Field>
          <Field label="Recipient (E.164)"><Input placeholder={data.env_set?.NAMMA_WHATSAPP_TO ? "(set)" : "e.g. 919876543210"} value={env.NAMMA_WHATSAPP_TO ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_WHATSAPP_TO: v }))} onBlur={() => commitEnv("NAMMA_WHATSAPP_TO")} /></Field>
        </>
      ) : (
        <>
          <Field label="Your number (E.164)"><Input placeholder={data.env_set?.NAMMA_WHATSAPP_TO ? "(set)" : "e.g. 919876543210"} value={env.NAMMA_WHATSAPP_TO ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_WHATSAPP_TO: v }))} onBlur={() => commitEnv("NAMMA_WHATSAPP_TO")} /></Field>
          <WhatsAppLink />
        </>
      )}
    </Section>
  );
}

// Polls /api/whatsapp/qr and renders the current link state: a QR to scan while
// unlinked, or a linked confirmation once the phone pairs the session. The QR only
// appears after the gateway is started (that's what opens the WhatsApp session).
export function WhatsAppLink() {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    const tick = () => fetchWhatsappQR().then((r) => { if (alive) setSt(r); });
    tick();
    const id = setInterval(tick, 2500);
    return () => { alive = false; clearInterval(id); };
  }, []);
  const reconnect = async () => {
    setBusy(true);
    await relinkWhatsapp();
    // Optimistically drop the linked state so the QR panel shows as soon as the
    // fresh QR is emitted; polling then reflects the real state.
    setSt((s) => (s ? { ...s, linked: false, qr: null } : s));
    setBusy(false);
  };
  const box = "rounded-lg border border-border p-3 text-sm";
  const btn = "px-3 py-1.5 rounded-lg border border-border hover:bg-accent-wash disabled:opacity-50";
  if (!st) return <div className={box}>Checking link status…</div>;
  if (!st.available) {
    if (!st.neonize)
      return <div className={box}>QR backend needs the <code>neonize</code> package (<code>pip install neonize</code>). If you just installed it, restart the app.</div>;
    // neonize is present but the qr backend isn't active on the server yet — it
    // was selected here but not applied.
    return <div className={box}>The QR backend is saved. <b>Start</b> the messaging gateway (top of this tab) to generate a QR to scan.</div>;
  }
  if (st.linked)
    return (
      <div className={box}>
        <div className="text-brand-deep mb-2">✅ WhatsApp is connected — the assistant can send and receive on your number.</div>
        <button onClick={reconnect} disabled={busy} className={btn}>{busy ? "Reconnecting…" : "Reconnect"}</button>
        <div className="text-xs text-fg-subtle mt-1.5">Reconnect unlinks this session and shows a new QR — use it to link a different phone.</div>
      </div>
    );
  if (st.qr)
    return (
      <div className={box}>
        <div className="mb-2">On your phone: <b>WhatsApp → Settings → Linked Devices → Link a device</b>, then scan:</div>
        <img src={st.qr} alt="WhatsApp linking QR code" className="w-44 h-44 bg-white rounded-md p-2" />
      </div>
    );
  return (
    <div className={box}>
      {busy ? "Generating a new QR…" : "Start the messaging gateway (top of this tab) to open the WhatsApp session and generate a QR to scan."}
    </div>
  );
}

// Settings → Messaging: the gateway, trust, and every channel's keys.
export function MessagingTab({ form }) {
  const { data, cur, setC, env, setEnv, commitEnv } = form;
  return (
    <>
      <GatewayControl />
      <TrustControl />
      <Section title="Telegram" hint="Chat with Namma Agent from your phone (outbound + inbound). Stored in .env.">
        <Field label="Bot token"><Input type="password" placeholder={data.env_set?.NAMMA_TELEGRAM_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_TELEGRAM_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_TELEGRAM_TOKEN: v }))} onBlur={() => commitEnv("NAMMA_TELEGRAM_TOKEN")} /></Field>
        <Field label="Chat id"><Input placeholder={data.env_set?.NAMMA_TELEGRAM_CHAT_ID ? "(set)" : "not set"} value={env.NAMMA_TELEGRAM_CHAT_ID ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_TELEGRAM_CHAT_ID: v }))} onBlur={() => commitEnv("NAMMA_TELEGRAM_CHAT_ID")} /></Field>
        <Toggle label="Reply to inbound Telegram messages" checked={!!cur("comms.inbound_enabled", true)} onChange={(v) => setC("comms.inbound_enabled", v)} />
      </Section>
      <Section title="Discord" hint="Webhook = send-only. To receive & reply, add a bot token (the bot dials out to Discord — works locally, no public URL). Enable the Message Content Intent in the Developer Portal.">
        <Field label="Webhook URL (outbound)"><Input type="password" placeholder={data.env_set?.NAMMA_DISCORD_WEBHOOK_URL ? "•••••• (set)" : "not set"} value={env.NAMMA_DISCORD_WEBHOOK_URL ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_DISCORD_WEBHOOK_URL: v }))} onBlur={() => commitEnv("NAMMA_DISCORD_WEBHOOK_URL")} /></Field>
        <Field label="Bot token (two-way)"><Input type="password" placeholder={data.env_set?.NAMMA_DISCORD_BOT_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_DISCORD_BOT_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_DISCORD_BOT_TOKEN: v }))} onBlur={() => commitEnv("NAMMA_DISCORD_BOT_TOKEN")} /></Field>
        <Field label="Channel id (optional)"><Input placeholder={data.env_set?.NAMMA_DISCORD_CHANNEL_ID ? "(set)" : "restrict to one channel"} value={env.NAMMA_DISCORD_CHANNEL_ID ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_DISCORD_CHANNEL_ID: v }))} onBlur={() => commitEnv("NAMMA_DISCORD_CHANNEL_ID")} /></Field>
      </Section>
      <Section title="Slack" hint="Webhook needs a public URL to receive. For local two-way use Socket Mode: add an app-level (xapp-) token + a bot (xoxb-) token and subscribe to message events — no public URL needed.">
        <Field label="Webhook URL (outbound)"><Input type="password" placeholder={data.env_set?.NAMMA_SLACK_WEBHOOK_URL ? "•••••• (set)" : "not set"} value={env.NAMMA_SLACK_WEBHOOK_URL ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SLACK_WEBHOOK_URL: v }))} onBlur={() => commitEnv("NAMMA_SLACK_WEBHOOK_URL")} /></Field>
        <Field label="App token (xapp-, Socket Mode)"><Input type="password" placeholder={data.env_set?.NAMMA_SLACK_APP_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_SLACK_APP_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SLACK_APP_TOKEN: v }))} onBlur={() => commitEnv("NAMMA_SLACK_APP_TOKEN")} /></Field>
        <Field label="Bot token (xoxb-, replies)"><Input type="password" placeholder={data.env_set?.NAMMA_SLACK_BOT_TOKEN ? "•••••• (set)" : "not set"} value={env.NAMMA_SLACK_BOT_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SLACK_BOT_TOKEN: v }))} onBlur={() => commitEnv("NAMMA_SLACK_BOT_TOKEN")} /></Field>
      </Section>
      <WhatsAppSettings env={env} setEnv={setEnv} commitEnv={commitEnv} data={data} />
      <Section title="Signal" hint="Outbound via a signal-cli REST API service.">
        <Field label="API URL"><Input placeholder={data.env_set?.NAMMA_SIGNAL_API_URL ? "(set)" : "http://localhost:8080"} value={env.NAMMA_SIGNAL_API_URL ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SIGNAL_API_URL: v }))} onBlur={() => commitEnv("NAMMA_SIGNAL_API_URL")} /></Field>
        <Field label="Sender number (E.164)"><Input placeholder={data.env_set?.NAMMA_SIGNAL_NUMBER ? "(set)" : "+919876543210"} value={env.NAMMA_SIGNAL_NUMBER ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SIGNAL_NUMBER: v }))} onBlur={() => commitEnv("NAMMA_SIGNAL_NUMBER")} /></Field>
        <Field label="Recipient / group id"><Input placeholder={data.env_set?.NAMMA_SIGNAL_RECIPIENT ? "(set)" : "not set"} value={env.NAMMA_SIGNAL_RECIPIENT ?? ""} onChange={(v) => setEnv((e) => ({ ...e, NAMMA_SIGNAL_RECIPIENT: v }))} onBlur={() => commitEnv("NAMMA_SIGNAL_RECIPIENT")} /></Field>
      </Section>
    </>
  );
}
