import { useState } from "react";
import Dialog from "./ui/Dialog.jsx";

// Secure sudo-password prompt. The value lives only in this component's local
// state until submit, then goes straight over the socket to sudo -S — it is never
// added to the chat, app state, or logs, and the field is cleared immediately.
export default function PasswordPrompt({ req, onSubmit, onCancel }) {
  const [value, setValue] = useState("");
  if (!req) return null;

  const submit = () => { onSubmit(value); setValue(""); };
  const cancel = () => { setValue(""); onCancel(); };

  return (
    <Dialog onClose={cancel} size="sm" labelledBy="sudo-title" className="p-5" dismissOnBackdrop={false}>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-lg">🔒</span>
          <h3 className="font-serif text-lg" id="sudo-title">{req.prompt || "Enter your sudo password"}</h3>
        </div>
        <p className="text-fg-muted text-sm mb-3">
          Used once for this command only. Never sent to the model, saved, or logged.
        </p>
        <input
          type="password" autoFocus value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") cancel(); }}
          placeholder="sudo password"
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 outline-none focus:border-brand"
        />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={cancel} className="px-4 py-2 rounded-lg text-fg-soft hover:bg-surface-hover">Cancel</button>
          <button onClick={submit} className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep">Authorize</button>
        </div>
    </Dialog>
  );
}
