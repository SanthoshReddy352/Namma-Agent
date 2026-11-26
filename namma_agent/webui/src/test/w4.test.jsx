// Phase 9 W4: Roman roles and personas: role emblems, Legatus on sub-agents,
// and the persona coin portraits on the profile rail.
import fs from "node:fs";
import path from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RoleEmblem from "../components/RoleEmblem.jsx";
import RunsPanel from "../components/RunsPanel.jsx";
import ProfileRail from "../components/shell/ProfileRail.jsx";
import { LEGATUS, MODES } from "../roles.js";

afterEach(() => { vi.restoreAllMocks(); });
const json = (body) => Promise.resolve(new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }));
const PUBLIC = path.resolve(__dirname, "..", "..", "public");

describe("roles", () => {
  it("gives each mode a Roman role with its own emblem, plus Legatus for sub-agents", () => {
    expect(MODES.map((m) => [m.id, m.role, m.emblem])).toEqual([
      ["agent", "Imperator", "imperator"], ["chat", "Scriba", "scriba"], ["setup", "Architectus", "architectus"],
    ]);
    expect(LEGATUS).toMatchObject({ role: "Legatus", emblem: "legatus" });
    for (const r of ["imperator", "scriba", "architectus", "legatus"]) {
      const { container, unmount } = render(<RoleEmblem role={r} size={20} />);
      const svg = container.querySelector("svg");
      expect(svg.getAttribute("data-emblem")).toBe(r);
      expect(svg.getAttribute("stroke")).toBe("currentColor");      // follows the theme
      expect(svg.children.length).toBeGreaterThan(1);
      unmount();
    }
  });

  it("marks delegated sub-agents as Legatus in the Runs pane, not background tasks", () => {
    render(<RunsPanel docked={false} runs={[
      { id: "r1", status: "running", kind: "subagent", name: "Find the ISS speed", goal: "Find the ISS speed" },
      { id: "r2", status: "running", kind: "background", name: "Index docs", goal: "Index docs" },
    ]} />);
    const marks = document.querySelectorAll('[data-role="legatus"]');
    expect(marks.length).toBe(1);
    expect(marks[0].closest("[data-run]").getAttribute("data-run")).toBe("r1");
    expect(marks[0].textContent).toBe("Legatus");
  });
});

describe("Roman personas", () => {
  it("ship a coin portrait for each of the five", () => {
    for (const p of ["caesar", "cicero", "augustus", "seneca", "aurelius"]) {
      const svg = fs.readFileSync(path.join(PUBLIC, "brand", "personas", `${p}.svg`), "utf8");
      expect(svg).toMatch(/^<svg[^>]+viewBox="0 0 120 120"/);
      expect(svg).toContain("Original art");
    }
  });

  it("show portraits and titles on the profile rail", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({
      active: "caesar",
      personas: [
        { id: "core", name: "Aria", portrait: null },
        { id: "caesar", name: "Caesar", title: "Dictator", tone: "decisive", portrait: "/brand/personas/caesar.svg" },
      ],
    }));
    render(<ProfileRail onManage={() => {}} />);
    const caesar = await screen.findByRole("radio", { name: "Persona: Caesar, Dictator" });
    expect(caesar.getAttribute("aria-checked")).toBe("true");
    expect(caesar.querySelector("img").getAttribute("src")).toBe("/brand/personas/caesar.svg");
    await waitFor(() => expect(screen.getByRole("radio", { name: "Persona: Aria" }).textContent).toBe("AR"));
  });
});

describe("side panel", () => {
  it("keeps its tabs out of the titlebar band, so the window controls never clip them", async () => {
    const { default: RightPane } = await import("../components/shell/RightPane.jsx");
    render(<RightPane runs={[]} todos={[]} messages={[]} />);
    const tabs = screen.getByRole("tablist", { name: "Side panel" });
    expect(tabs.closest("[data-chrome]")).toBeNull();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Runs", "Plan", "Files", "Preview"]);
  });
});
