// Phase 9: the same UI runs in the browser and inside the Electron desktop app
// (W3). The desktop preload exposes `window.nammaDesktop`; everything here
// feature-detects it, so the web build never assumes it exists.
export const desktop = () => (typeof window !== "undefined" ? window.nammaDesktop || null : null);
export const isDesktop = () => !!desktop();
