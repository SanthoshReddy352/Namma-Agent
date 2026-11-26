// Phase 9 W3: the desktop bridge (src/desktop.js) — title bar overlay colours and
// shell events. In the browser (no window.nammaDesktop) it must do nothing.
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  delete window.nammaDesktop;
  document.documentElement.className = "";
  document.documentElement.removeAttribute("style");
  document.body.innerHTML = "";
  vi.resetModules();
});

describe("toHex", () => {
  it("reads our token triplets, rgb(), rgba() and hex", async () => {
    const { toHex } = await import("../desktop.js");
    expect(toHex(" 246 248 252")).toBe("#f6f8fc");
    expect(toHex("rgb(16, 19, 26)")).toBe("#10131a");
    expect(toHex("rgba(16, 19, 26, 0.5)")).toBe("#10131a");
    expect(toHex("#ABCDEF")).toBe("#abcdef");
  });
  it("treats transparent and junk as no colour", async () => {
    const { toHex } = await import("../desktop.js");
    expect(toHex("rgba(0, 0, 0, 0)")).toBeNull();
    expect(toHex("transparent")).toBeNull();
    expect(toHex("")).toBeNull();
  });
});

describe("in the browser", () => {
  it("is a no-op without the preload", async () => {
    const mod = await import("../desktop.js");
    expect(mod.isDesktop()).toBe(false);
    expect(mod.initDesktop()).toBe(false);
  });
});

describe("in the desktop app", () => {
  const fakeShell = () => {
    const calls = [];
    let listener = null;
    window.nammaDesktop = {
      setTitleBarOverlay: (o) => calls.push(o),
      onEvent: (cb) => { listener = cb; return () => {}; },
    };
    return { calls, emit: (ev) => listener && listener(ev) };
  };

  it("sends the theme's ink and the band colour, and follows theme changes", async () => {
    const shell = fakeShell();
    document.documentElement.style.setProperty("--bg", "246 248 252");
    document.documentElement.style.setProperty("--fg", "16 19 26");
    const band = document.createElement("div");
    band.style.backgroundColor = "rgb(1, 2, 3)";
    document.body.appendChild(band);
    document.elementFromPoint = () => band;
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => { cb(); return 1; });
    await import("../desktop.js");
    expect(shell.calls.at(-1)).toMatchObject({ color: "#010203", symbolColor: "#10131a", background: "#f6f8fc", height: 34, dark: false });

    // Theme switch: the <html> class changes and new tokens apply.
    document.documentElement.style.setProperty("--fg", "230 232 238");
    band.style.backgroundColor = "rgb(20, 22, 28)";
    document.documentElement.classList.add("dark", "theme-imperium");
    await new Promise((r) => setTimeout(r, 0));
    expect(shell.calls.at(-1)).toMatchObject({ color: "#14161c", symbolColor: "#e6e8ee", dark: true });
    const n = shell.calls.length;
    document.documentElement.classList.add("theme-imperium"); // no visual change → nothing sent
    await new Promise((r) => setTimeout(r, 0));
    expect(shell.calls.length).toBe(n);
  });

  it("falls back to --bg when nothing opaque is under the controls", async () => {
    const shell = fakeShell();
    document.documentElement.style.setProperty("--bg", "10 11 12");
    document.documentElement.style.setProperty("--fg", "250 250 250");
    document.elementFromPoint = () => null;
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => { cb(); return 1; });
    await import("../desktop.js");
    expect(shell.calls.at(-1)).toMatchObject({ color: "#0a0b0c", symbolColor: "#fafafa" });
  });

  it("routes deep links and tray actions", async () => {
    const shell = fakeShell();
    document.elementFromPoint = () => null;
    const pops = [];
    window.addEventListener("popstate", () => pops.push(location.pathname));
    await import("../desktop.js");
    shell.emit({ type: "navigate", route: "/settings/notifications" });
    expect(location.pathname).toBe("/settings/notifications");
    expect(pops.at(-1)).toBe("/settings/notifications");
    shell.emit({ type: "navigate", route: "https://evil.example/" });
    expect(location.pathname).toBe("/settings/notifications");

    const clicked = vi.fn();
    const btn = document.createElement("button");
    btn.setAttribute("aria-label", "New chat");
    btn.onclick = clicked;
    document.body.appendChild(btn);
    shell.emit({ type: "new-chat" });
    expect(location.pathname).toBe("/");
    expect(clicked).toHaveBeenCalledTimes(1);
  });
});
