// Clipboard helpers.
//
// The real reason copy/paste was dead inside the desktop window is the host:
// WebKit2GTK (the Linux pywebview backend) disables JS clipboard access by
// default, which the app now turns on natively at launch (see app.py). With that
// fixed, the OS-level Ctrl+C / Ctrl+V / Ctrl+X work normally in inputs and on
// selections — so the JS layer here stays PURELY ADDITIVE: it never calls
// preventDefault and never re-implements paste (doing so previously suppressed the
// working native copy and could double-paste). `copyText` backs the explicit copy
// buttons; the keydown hook just mirrors a selection-copy to the clipboard as a
// best-effort safety net for hosts where native copy still misbehaves.

// Write arbitrary text to the clipboard. Returns true on success.
export async function copyText(text) {
  const value = String(text ?? "");
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch { /* fall through to the execCommand path */ }
  try {
    const prev = document.activeElement; // restore focus after the copy hack
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    if (prev && typeof prev.focus === "function") prev.focus();
    return ok;
  } catch {
    return false;
  }
}

// Best-effort safety net: mirror a Ctrl/Cmd+C selection to the clipboard via the
// async API WITHOUT preventing the native copy. Cut and paste are left entirely
// to the host (native editing), so this can never suppress a working shortcut or
// double-insert on paste. Returns an unsubscribe function.
export function installClipboardShortcuts() {
  const onKeyDown = (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    if (e.key.toLowerCase() !== "c") return;
    const el = document.activeElement;
    const inInput = el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT");
    // Let inputs copy their own selection natively; only help for page selections.
    if (inInput) return;
    const text = window.getSelection?.().toString() || "";
    if (text && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).catch(() => { /* native copy still runs */ });
    }
  };
  window.addEventListener("keydown", onKeyDown, true);
  return () => window.removeEventListener("keydown", onKeyDown, true);
}
