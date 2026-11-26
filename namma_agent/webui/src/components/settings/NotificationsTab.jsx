// Settings → NotificationsTab (split out of Settings.jsx, Phase 9 W1).

import { useEffect, useState } from "react";
import { COMPLETION_PRESETS, SOUND_EVENTS, completionPreset, previewPreset, setCompletionPreset, setSoundEventEnabled, setSoundVolume, setSoundsEnabled, soundEventEnabled, soundVolume, soundsEnabled } from "../../sounds.js";
import { NOTIFY_EVENTS, notifyEnabled, notifyEventEnabled, notifyStatus, sendTestNotification, setNotifyEnabled, setNotifyEventEnabled } from "../../notify.js";
import { Block, ToggleCard, _btnGhost } from "./shared.jsx";
import { IconPlayerPlayFilled } from "@tabler/icons-react";

// The "Notifications" tab — Phases 5 + 6. Two halves, both client-only
// (localStorage, like the theme — no Save round-trip):
//   • Desktop notifications — native OS toasts delivered by the backend (reliable
//     inside the pywebview window): master switch, per-event toggles, a test button.
//   • Sounds — synthesised interaction cues: master switch, volume, the completion
//     -sound preset picker (click to set & hear, ▶ to preview), per-event toggles.
export function NotificationsTab() {
  // ── Desktop notifications ──
  const [notif, setNotif] = useState(notifyEnabled());
  const [notifEvents, setNotifEvents] = useState(
    () => Object.fromEntries(NOTIFY_EVENTS.map((e) => [e.id, notifyEventEnabled(e.id)])));
  const [testMsg, setTestMsg] = useState("");
  // Whether the OS will actually render a toast — surfaced up front so a machine
  // with notifications switched off says so, instead of silently showing nothing.
  const [osStatus, setOsStatus] = useState(null); // {available, reason}

  useEffect(() => { notifyStatus().then(setOsStatus); }, []);

  const flipNotif = (v) => { setNotif(v); setNotifyEnabled(v); };
  const flipNotifEvent = (id, v) => { setNotifEvents((e) => ({ ...e, [id]: v })); setNotifyEventEnabled(id, v); };
  const test = async () => {
    const { ok, reason } = await sendTestNotification();
    notifyStatus().then(setOsStatus);  // the user may have just fixed it
    setTestMsg(ok
      ? "Sent — check your desktop."
      : (reason || "Your OS wouldn't show it — displayed in the app instead."));
    setTimeout(() => setTestMsg(""), 8000);
  };

  // ── Sounds ──
  const [on, setOn] = useState(soundsEnabled());
  const [vol, setVol] = useState(soundVolume());
  const [preset, setPreset] = useState(completionPreset());
  const [sndEvents, setSndEvents] = useState(
    () => Object.fromEntries(SOUND_EVENTS.map((e) => [e.id, soundEventEnabled(e.id)])));

  const flipOn = (v) => { setOn(v); setSoundsEnabled(v); };
  const changeVol = (v) => { setVol(v); setSoundVolume(v); };
  const choosePreset = (id) => { setPreset(id); setCompletionPreset(id); previewPreset(id); };
  const flipSndEvent = (id, v) => { setSndEvents((e) => ({ ...e, [id]: v })); setSoundEventEnabled(id, v); };

  return (
    <div className="space-y-8">
      {/* ── Desktop notifications ── */}
      <Block title="Desktop notifications"
             hint="Native pop-ups from your OS when a reply is ready or your assistant needs you — they reach you even when the window is in the background.">
        <ToggleCard rows={[{ id: "master", label: "Enable notifications", checked: notif, onChange: flipNotif }]} />
        {osStatus && !osStatus.available && osStatus.reason && (
          <div className="rounded-lg border border-amber-400/50 bg-amber-50 dark:bg-amber-500/10 px-3 py-2 text-xs text-fg-muted">
            {osStatus.reason} Until then, notifications appear as banners inside the app.
          </div>
        )}
        <div className="space-y-2">
          <div className="text-xs font-medium text-fg-muted">Notify me about</div>
          <ToggleCard disabled={!notif}
                      rows={NOTIFY_EVENTS.map((e) => ({ id: e.id, label: e.label, checked: notifEvents[e.id], onChange: (v) => flipNotifEvent(e.id, v) }))} />
        </div>
        <div className="flex items-center gap-3 pt-0.5">
          <button onClick={test} className={_btnGhost}>Send test notification</button>
          {testMsg && <span className="text-xs text-fg-subtle">{testMsg}</span>}
        </div>
      </Block>

      <div className="border-t border-border" />

      {/* ── Sounds ── */}
      <Block title="Interaction sounds"
             hint="Short, synthesised cues on the moments of a turn — sent, each action step, and the reply landing. They play in your browser; nothing is sent anywhere.">
        <ToggleCard rows={[{ id: "snd", label: "Enable sounds", checked: on, onChange: flipOn }]} />
        <div className={"flex items-center gap-3 " + (on ? "" : "opacity-50 pointer-events-none")}>
          <span className="text-sm text-fg-muted w-20 shrink-0">Volume</span>
          <input type="range" min="0" max="1" step="0.05" value={vol}
                 onChange={(e) => changeVol(parseFloat(e.target.value))} disabled={!on} className="flex-1" />
          <span className="text-xs tabular-nums text-fg-subtle w-9 text-right">{Math.round(vol * 100)}%</span>
        </div>
      </Block>

      <Block title="Completion sound" hint="The sound when a reply is ready. Click a preset to set it and hear it; ▶ previews without changing your pick.">
        <div className={`grid grid-cols-2 gap-2.5 ${on ? "" : "opacity-50 pointer-events-none"}`}>
          {COMPLETION_PRESETS.map((p) => {
            const active = preset === p.id;
            return (
              <button key={p.id} type="button" onClick={() => choosePreset(p.id)}
                      className={"flex items-center justify-between gap-2 rounded-xl border px-3.5 py-2.5 text-left text-sm transition " +
                        (active ? "border-brand ring-2 ring-brand/30 bg-accent-wash" : "border-border hover:border-brand/50")}>
                <span className="truncate text-fg">{p.label}</span>
                <span role="button" tabIndex={-1} className="shrink-0 grid place-items-center h-6 w-6 rounded-full text-fg-subtle hover:bg-paper-soft dark:hover:bg-night-line" title="Preview"
                      onClick={(e) => { e.stopPropagation(); previewPreset(p.id); }}>
                  <IconPlayerPlayFilled size={12} aria-hidden="true" />
                </span>
              </button>
            );
          })}
        </div>
      </Block>

      <Block title="Play a sound for" hint="Turn individual cues off without muting everything.">
        <ToggleCard disabled={!on}
                    rows={SOUND_EVENTS.map((e) => ({ id: e.id, label: e.label, checked: sndEvents[e.id], onChange: (v) => flipSndEvent(e.id, v) }))} />
      </Block>
    </div>
  );
}
