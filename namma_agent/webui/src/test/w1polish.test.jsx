// Phase 9 W1, slice 5 (owner feedback): corner art, legibility, the sidebar,
// the medallion logo, click sounds, scrollbars, sub-agent details, and the
// redesigned Projects / Learning Room pages.
import fs from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import RunsPanel, { runBrief } from "../components/RunsPanel.jsx";
import Logo from "../components/Logo.jsx";
import Sidebar from "../components/Sidebar.jsx";
import ProjectsView from "../views/ProjectsView.jsx";
import LearningView, { nextModule, topicProgress } from "../views/LearningView.jsx";
import { CLICKABLE, SOUND_EVENTS, clickTarget, installClickSounds } from "../sounds.js";

const SRC = path.resolve(__dirname, "..");
const css = () => fs.readFileSync(path.join(SRC, "index.css"), "utf8");
const json = (body) => Promise.resolve({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body });
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("sub-agent details", () => {
  const run = {
    id: "r1", name: "ISS research", goal: "Find the ISS speed", status: "completed", steps: 2, depth: 1,
    child_session_id: "child1", summary: "About 7.66 km/s.", tools_used: ["web_search"],
    meta: {
      prompt: "GOAL: Find the ISS speed\n\nCONTEXT FROM THE MAIN AGENT:\nstudent", step_limit: 12,
      toolsets: ["web"], skills: ["deep-research"],
      trail: [{ tool: "web_search", args: "{\"query\": \"iss speed\"}", status: "ok", result: "5 results" }],
    },
  };

  it("opens a run to show its brief, budget, chips, steps, result and transcript", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ turns: [{ role: "user", content: "GOAL: Find the ISS speed" }, { role: "assistant", content: "7.66 km/s" }] }));
    render(<RunsPanel runs={[run]} docked={false} />);
    expect(screen.getByText(/completed · 2\/12 steps/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show details for ISS research" }));
    expect(screen.getByText(/CONTEXT FROM THE MAIN AGENT:/)).toBeTruthy();
    expect(screen.getByText("web")).toBeTruthy();
    expect(screen.getByText("skill: deep-research")).toBeTruthy();
    expect(screen.getByText("web_search")).toBeTruthy();
    expect(screen.getByText(/5 results/)).toBeTruthy();
    expect(screen.getByText("About 7.66 km/s.")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /transcript/ })); });
    expect(await screen.findByText("7.66 km/s")).toBeTruthy();
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/sessions/child1");
  });

  it("rebuilds the brief for older runs that predate stored prompts", () => {
    expect(runBrief({ goal: "g", meta: { context: "c" } })).toBe("GOAL: g\n\nCONTEXT FROM THE MAIN AGENT:\nc");
    expect(runBrief({ goal: "g" })).toBe("GOAL: g");
  });
});

describe("sidebar", () => {
  const renderSidebar = () => render(
    <MemoryRouter><Sidebar sessions={[]} projects={[]} onNew={() => {}} name="Namma Agent" /></MemoryRouter>);

  it("only the toggle changes it: hovering never expands or collapses", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ personas: [] }));
    localStorage.setItem("namma-sidebar-pinned", "false");
    renderSidebar();
    const aside = screen.getByRole("complementary", { name: "Sidebar" });
    expect(aside.dataset.expanded).toBe("false");
    fireEvent.mouseEnter(aside);
    expect(aside.dataset.expanded).toBe("false");
    act(() => { window.dispatchEvent(new Event("namma-toggle-sidebar")); });
    expect(aside.dataset.expanded).toBe("true");
    fireEvent.mouseLeave(aside);
    expect(aside.dataset.expanded).toBe("true");
  });

  it("puts the brand on its own row with the highlighted medallion", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ personas: [] }));
    renderSidebar();
    const home = screen.getByRole("button", { name: "Namma Agent — home" });
    expect(home.querySelector(".brand-medallion")).toBeTruthy();
  });
});

describe("logo", () => {
  it("medallion fills the silhouette and uses bold lines at small sizes", () => {
    const { container, rerender } = render(<Logo size={88} variant="medallion" />);
    expect(container.querySelector(".brand-medallion-fill")).toBeTruthy();
    expect(container.querySelector(".brand-medallion-ink").className).not.toContain("brand-logo-bold");
    rerender(<Logo size={34} variant="medallion" />);
    expect(container.querySelector(".brand-medallion-ink").className).toContain("brand-logo-bold");
    for (const f of ["logo-fill.png", "logo-mask-bold.png"]) expect(fs.existsSync(path.join(SRC, "..", "public", "brand", f))).toBe(true);
  });
});

describe("click sounds", () => {
  it("plays on button-like controls only, and never on disabled ones", () => {
    document.body.innerHTML = '<button id="b"><span id="inner">x</span></button><button id="d" disabled></button><div id="plain"></div><div role="tab" id="t"></div>';
    expect(clickTarget(document.getElementById("inner")).id).toBe("b");
    expect(clickTarget(document.getElementById("d"))).toBeNull();
    expect(clickTarget(document.getElementById("plain"))).toBeNull();
    expect(clickTarget(document.getElementById("t")).id).toBe("t");
    expect(CLICKABLE).toContain('[role="option"]');
    expect(SOUND_EVENTS.map((e) => e.id)).toContain("click");
  });

  it("the global listener synthesises a short tick (and respects the toggle)", () => {
    const osc = vi.fn(() => ({ type: "", frequency: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (x) => x, start() {}, stop() {} }));
    const gain = () => ({ gain: { value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (x) => x });
    window.AudioContext = vi.fn(function AC() { return { state: "running", currentTime: 0, destination: {}, createOscillator: osc, createGain: gain }; });
    document.body.innerHTML = '<button id="b">go</button>';
    const off = installClickSounds(document);
    fireEvent.pointerDown(document.getElementById("b"), { button: 0 });
    expect(osc).toHaveBeenCalledTimes(2);                 // transient + body
    localStorage.setItem("namma-sound-events", JSON.stringify({ click: false }));
    fireEvent.pointerDown(document.getElementById("b"), { button: 0 });
    expect(osc).toHaveBeenCalledTimes(2);
    off();
  });
});

describe("chat background and chrome", () => {
  it("feathers each corner piece out of its edge and blends it into the paper", () => {
    const c = css();
    expect(c).toMatch(/\.chat-bg-art \{[^}]*mix-blend-mode: var\(--art-blend\)/);
    expect(c).toMatch(/\.chat-bg-art \{[^}]*mask-composite: intersect/);
    expect(c).toMatch(/\.chat-bg-art-drip \{[^}]*top: 0;/);
    expect(c).toMatch(/\.chat-bg-art-rise \{[^}]*bottom: 0;/);
    expect(c).not.toContain("art-hands");
    expect(c).toMatch(/\.chat-legible \{[^}]*text-shadow:/);
  });

  it("uses ultra-thin, faint scrollbars everywhere", () => {
    const c = css();
    expect(c).toMatch(/::-webkit-scrollbar \{ width: 4px; height: 4px; \}/);
    expect(c).toMatch(/scrollbar-color: rgb\(var\(--fg\) \/ 0\.12\) transparent/);
  });

  it("opens Settings wider", () => {
    const shell = fs.readFileSync(path.join(SRC, "components", "Settings.jsx"), "utf8");
    expect(shell).toContain('size="xl"');
    expect(fs.readFileSync(path.join(SRC, "components", "ui", "Dialog.jsx"), "utf8")).toContain('"w-[1120px]"');
  });
});

describe("redesigned pages", () => {
  const withCtx = (el, ctx) => render(
    <MemoryRouter><Routes><Route element={<Outlet context={ctx} />}><Route path="/" element={el} /></Route></Routes></MemoryRouter>);

  it("Projects: header action + stats, tone-striped cards, idea chips when empty", () => {
    const projects = [{ id: "a", name: "Garden", description: "Terrace plants", chat_count: 2, updated_at: new Date().toISOString() }];
    const { unmount } = withCtx(<ProjectsView />, { projects, refreshProjects() {}, confirmAction: async () => false });
    expect(screen.getByRole("button", { name: /New project/ })).toBeTruthy();
    expect(screen.getByText("Garden")).toBeTruthy();
    expect(screen.getByText(/2 chats/)).toBeTruthy();
    unmount();
    withCtx(<ProjectsView />, { projects: [], refreshProjects() {} });
    fireEvent.click(screen.getByRole("button", { name: "Thesis research" }));
    expect(screen.getByDisplayValue("Thesis research")).toBeTruthy();       // idea pre-fills the dialog
  });

  it("Learning Room: continue card, progress rings, next module", async () => {
    const topics = [
      { id: "t1", title: "Neural nets", depth: "solid", plan: [{ id: "1", title: "Neurons", status: "done" }, { id: "2", title: "Backprop", status: "todo" }] },
    ];
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ topics }));
    withCtx(<LearningView />, { confirmAction: async () => false });
    const cont = await screen.findByTestId("continue-learning");
    expect(cont.textContent).toContain("Up next: Backprop");
    expect(screen.getAllByRole("img", { name: "50% complete" }).length).toBe(2);
    expect(topicProgress(topics[0])).toEqual({ done: 1, total: 2, pct: 50 });
    expect(nextModule(topics[0]).title).toBe("Backprop");
  });
});

describe("sidebar: chats appear the moment they start", () => {
  it("shows a pending chat as an italic 'Untitled session', pulsing only while its turn runs", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ personas: [] }));
    const onOpen = vi.fn();
    render(<MemoryRouter><Sidebar sessions={[{ id: "s1", title: "Untitled session", pending: true }, { id: "s2", title: "Weekly Plan" }]}
                                  projects={[]} busySessions={["s1"]} onNew={() => {}} onOpen={onOpen} name="Namma Agent" /></MemoryRouter>);
    const pending = screen.getByText("Untitled session").closest("button");
    expect(pending.dataset.pending).toBe("true");
    expect(screen.getAllByLabelText("Working")).toHaveLength(1);         // only the busy one
    expect(screen.getByText("Weekly Plan").closest("button").dataset.pending).toBeUndefined();
    fireEvent.click(pending);
    expect(onOpen).toHaveBeenCalledWith("s1");
  });
});
