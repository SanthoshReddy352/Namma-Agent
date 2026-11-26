import fs from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChatBackdrop, { BACKDROP_LAYERS, MODE_PAINTS } from "../components/ChatBackdrop.jsx";
import Logo from "../components/Logo.jsx";

const ROOT = path.resolve(__dirname, "..", "..");

describe("brand art (owner's images)", () => {
  it("layers paint, line art, crumpled paper and a veil, all decorative", () => {
    render(<ChatBackdrop />);
    const bd = screen.getByTestId("chat-backdrop");
    expect(bd.getAttribute("aria-hidden")).toBe("true");
    expect(bd.className).toContain("pointer-events-none");
    expect([...bd.querySelectorAll("[data-layer]")].map((e) => e.dataset.layer)).toEqual(BACKDROP_LAYERS);
    expect(bd.dataset.mode).toBe("agent");
    expect(bd.dataset.busy).toBeUndefined();
  });

  it("paints in the current mode's colour and lets the ink flow while busy", () => {
    const { rerender } = render(<ChatBackdrop mode="chat" busy />);
    const bd = screen.getByTestId("chat-backdrop");
    expect(bd.dataset.mode).toBe("chat");
    expect(bd.dataset.busy).toBe("true");
    const before = bd.querySelector('[data-layer="wash-b"]');
    rerender(<ChatBackdrop mode="setup" />);
    expect(bd.dataset.mode).toBe("setup");
    // Re-keyed on mode, so the bloom animation replays.
    expect(bd.querySelector('[data-layer="wash-b"]')).not.toBe(before);
    rerender(<ChatBackdrop mode="nonsense" />);
    expect(bd.dataset.mode).toBe("agent");
    expect(Object.keys(MODE_PAINTS)).toEqual(["agent", "chat", "setup"]);
  });

  it("colours every layer from theme tokens, light and dark", () => {
    const css = fs.readFileSync(path.join(ROOT, "src", "index.css"), "utf8");
    expect(css).toMatch(/\.chat-bg \{[^}]*--paint-a: var\(--brand\)/);
    expect(css).toMatch(/\.dark \.chat-bg \{[^}]*--paint-a: var\(--accent-bright\)/);
    for (const m of ["agent", "chat", "setup"]) {
      expect(css).toContain(`.chat-bg[data-mode="${m}"]`);
      expect(css).toContain(`.dark .chat-bg[data-mode="${m}"]`);
    }
    expect(css).toMatch(/\.chat-bg-wash-a \{[^}]*rgb\(var\(--paint-a\)/);
    expect(css).toMatch(/\.chat-bg-wash-b \{[^}]*rgb\(var\(--paint-b\)/);
    expect(css).toMatch(/\.chat-bg-art \{[^}]*rgb\(var\(--bg-ink\)/);
    expect(css).toMatch(/\.chat-bg-paper \{[^}]*mix-blend-mode: var\(--paper-blend\)/);
    expect(css).not.toContain("chat-background.webp");
  });

  it("ships the masks and icons the UI and installers reference", () => {
    for (const f of ["logo-mask.png", "bg/wash-a.webp", "bg/wash-b.webp", "bg/paper.webp", "bg/paper-shade.webp", "bg/art-drip.webp", "bg/art-masks.webp", "bg/art-hands.webp", "favicon.ico", "icon-32.png", "icon-180.png", "icon-512.png"]) {
      expect(fs.existsSync(path.join(ROOT, "public", "brand", f))).toBe(true);
    }
    const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
    expect(html).toContain("/brand/favicon.ico");
  });

  it("renders the logo as a decorative mask, or a named image when titled", () => {
    const { container, rerender } = render(<Logo size={40} />);
    const el = container.querySelector(".brand-logo");
    expect(el.getAttribute("aria-hidden")).toBe("true");
    expect(el.style.width).toBe("40px");
    rerender(<Logo size={40} title="Namma Agent" />);
    expect(screen.getByRole("img", { name: "Namma Agent" })).toBeTruthy();
  });
});
