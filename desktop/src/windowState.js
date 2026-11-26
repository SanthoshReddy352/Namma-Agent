// Remembers the window's size, position and maximized state between launches,
// and never restores it off-screen (a monitor that was unplugged, a lower DPI).
"use strict";

const DEFAULT = { width: 1200, height: 800 };
const MIN = { width: 720, height: 560 };

function intersects(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

// Pure: given the saved state and the displays' work areas, the bounds to open
// with. A saved rect must overlap a display by at least 100x50 px (enough to grab
// the band and drag it back); otherwise it's centred on the primary display.
function restoreBounds(saved, workAreas, primary) {
  const area = primary || workAreas[0] || { x: 0, y: 0, width: 1280, height: 800 };
  let width = Math.max(MIN.width, Math.round((saved && saved.width) || DEFAULT.width));
  let height = Math.max(MIN.height, Math.round((saved && saved.height) || DEFAULT.height));
  if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
    const rect = { x: saved.x, y: saved.y, width, height };
    const visible = workAreas.some((wa) => {
      if (!intersects(rect, wa)) return false;
      const w = Math.min(rect.x + rect.width, wa.x + wa.width) - Math.max(rect.x, wa.x);
      const h = Math.min(rect.y + rect.height, wa.y + wa.height) - Math.max(rect.y, wa.y);
      return w >= 100 && h >= 50;
    });
    if (visible) return { x: rect.x, y: rect.y, width, height, maximized: !!saved.maximized };
  }
  width = Math.min(width, Math.round(area.width * 0.92));
  height = Math.min(height, Math.round(area.height * 0.9));
  return {
    x: Math.round(area.x + (area.width - width) / 2),
    y: Math.round(area.y + (area.height - height) / 2),
    width, height, maximized: !!(saved && saved.maximized),
  };
}

// Wire a BrowserWindow to the store: save (debounced) on move/resize/maximize,
// and on close. The normal (un-maximized) bounds are kept while maximized.
function track(win, store, key = "window") {
  let timer = null;
  const save = () => {
    if (win.isDestroyed()) return;
    const prev = store.get(key) || {};
    const maximized = win.isMaximized();
    const b = maximized || win.isMinimized() ? (prev.x != null ? prev : win.getNormalBounds()) : win.getBounds();
    store.set(key, { x: b.x, y: b.y, width: b.width, height: b.height, maximized });
  };
  const soon = () => { clearTimeout(timer); timer = setTimeout(save, 400); };
  for (const ev of ["resize", "move", "maximize", "unmaximize"]) win.on(ev, soon);
  win.on("close", () => { clearTimeout(timer); save(); });
}

module.exports = { restoreBounds, track, DEFAULT, MIN };
