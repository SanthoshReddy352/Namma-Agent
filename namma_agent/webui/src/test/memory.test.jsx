// Phase 10 — the Memory page: graph model helpers, the canvas graph's
// controls, the Schema and Ranked tabs, and the page wiring (search → focus →
// entity panel with its source facts).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  edgeCurvature, layoutGraph, neighbourhood, nodeRadius, relLabel, searchNodes, typeGroups, typeToken,
} from "../components/memory/graphModel.js";
import MemoryGraph from "../components/MemoryGraph.jsx";
import SchemaView from "../components/memory/SchemaView.jsx";
import RankedView from "../components/memory/RankedView.jsx";
import MemoryView from "../views/MemoryView.jsx";

const json = (body) => Promise.resolve({
  ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body,
});

const NODES = [
  { id: "u", label: "Santhosh", type: "person", is_self: true, score: 0.98, degree: 4, aliases: [], attributes: { age: "21" } },
  { id: "k", label: "Kalasalingam Academy of Research and Education", type: "organization", score: 0.3, degree: 1, aliases: ["KARE"] },
  { id: "p", label: "Python", type: "technology", score: 0.5, degree: 1, aliases: ["python"] },
  { id: "a", label: "Arjun", type: "person", score: 0.52, degree: 2, aliases: [] },
  { id: "n", label: "Namma Agent", type: "project", score: 0.51, degree: 2, aliases: ["Namma Agent project"] },
];
const EDGES = [
  { id: "e1", source: "u", target: "k", rel: "studies_at", relation: "studies at", directed: true, confidence: 0.7 },
  { id: "e2", source: "u", target: "p", rel: "likes", relation: "likes", directed: true, confidence: 0.91 },
  { id: "e3", source: "u", target: "a", rel: "works_with", relation: "works with", directed: false, confidence: 0.7 },
  { id: "e4", source: "u", target: "a", rel: "meeting_with", relation: "meeting with", directed: true, confidence: 0.7 },
  { id: "e5", source: "a", target: "n", rel: "works_on", relation: "works on", directed: true, confidence: 0.7 },
  { id: "e6", source: "u", target: "n", rel: "lives_in", relation: "lives in", directed: true, expired: true },
];
const SCHEMA = {
  ok: true,
  types: [
    { type: "person", count: 2, attributes: ["age"], examples: ["Santhosh", "Arjun"] },
    { type: "technology", count: 1, attributes: [], examples: ["Python"] },
    { type: "project", count: 1, attributes: [], examples: ["Namma Agent"] },
  ],
  relations: [
    { rel: "works_on", label: "works on", count: 2, symmetric: false, functional: false,
      pairs: [{ source: "person", target: "project", count: 2 }] },
    { rel: "works_with", label: "works with", count: 1, symmetric: true, functional: false,
      pairs: [{ source: "person", target: "person", count: 1 }] },
    { rel: "lives_in", label: "lives in", count: 1, symmetric: false, functional: true,
      pairs: [{ source: "person", target: "place", count: 1 }] },
  ],
  counts: { types: 3, relations: 3, entities: 4, edges: 4 },
};
const RANKED = {
  ok: true, weights: { centrality: 0.45, salience: 0.3, recency: 0.25 }, half_life_days: 30,
  items: [
    { id: "u", name: "Santhosh", type: "person", is_self: true, score: 0.98, centrality: 1, salience: 0.96, recency: 0.95, degree: 4, facts: 6, last_seen: new Date().toISOString() },
    { id: "a", name: "Arjun", type: "person", is_self: false, score: 0.52, centrality: 0.24, salience: 0.57, recency: 0.95, degree: 2, facts: 2 },
    { id: "n", name: "Namma Agent", type: "project", is_self: false, score: 0.51, centrality: 0.34, salience: 0.77, recency: 0.5, degree: 2, facts: 2 },
  ],
};

beforeEach(() => {
  // jsdom has no 2D canvas; the component must cope (it draws nothing).
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});
afterEach(() => { vi.restoreAllMocks(); });

describe("graph model", () => {
  it("gives each canonical type a fixed theme token and hashes unknown types onto the palette", () => {
    expect(typeToken("person")).toBe("chart-1");
    expect(typeToken("organization")).toBe("chart-2");
    expect(typeToken("concept")).toBe("fg-subtle");
    expect(typeToken("Recipe")).toMatch(/^chart-[1-8]$/);
    expect(typeToken("recipe")).toBe(typeToken("recipe"));
  });

  it("orders the legend by the canonical type order with counts", () => {
    expect(typeGroups(NODES).map((g) => [g.type, g.count])).toEqual([
      ["person", 2], ["organization", 1], ["project", 1], ["technology", 1]]);
  });

  it("finds a node's live neighbourhood (superseded edges excluded)", () => {
    expect([...neighbourhood("n", EDGES)].sort()).toEqual(["a", "n"]);
    expect(neighbourhood(null, EDGES).size).toBe(0);
  });

  it("searches labels and aliases, prefix matches first", () => {
    expect(searchNodes(NODES, "kare").map((n) => [n.id, n.via])).toEqual([["k", "KARE"]]);
    expect(searchNodes(NODES, "a")[0].id).toBe("a");          // "Arjun" starts with a
    expect(searchNodes(NODES, "")).toEqual([]);
  });

  it("fans parallel edges out and keeps single edges straight", () => {
    const c = edgeCurvature(EDGES);
    expect(c.e1).toBe(0);
    expect(c.e3).not.toBe(c.e4);
    expect(Math.abs(c.e3)).toBe(Math.abs(c.e4));
  });

  it("lays the graph out deterministically, finite and without overlaps", () => {
    const a = layoutGraph(NODES, EDGES), b = layoutGraph(NODES, EDGES);
    expect(a).toEqual(b);
    const pts = Object.values(a);
    expect(pts).toHaveLength(NODES.length);
    for (const p of pts) { expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true); }
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        expect(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y)).toBeGreaterThan(30);
      }
    }
  });

  it("sizes the user's node above the floor and labels relations readably", () => {
    expect(nodeRadius(NODES[0])).toBeGreaterThan(nodeRadius(NODES[1]));
    expect(relLabel("studies_at")).toBe("studies at");
  });
});

describe("MemoryGraph", () => {
  it("renders the type legend, accessible summary and view controls", () => {
    const onSelect = vi.fn();
    render(<MemoryGraph nodes={NODES} edges={EDGES} onSelect={onSelect} height={400} />);
    expect(screen.getByRole("img", { name: /5 entities, 6 relations/ })).toBeTruthy();
    const legend = screen.getByLabelText("Entity types");
    expect(within(legend).getByText("person")).toBeTruthy();
    expect(within(legend).getByText("2")).toBeTruthy();
    for (const name of ["Zoom in", "Zoom out", "Fit to view", "Show all labels"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
  });

  it("hides a type from the legend toggle and updates the summary", () => {
    render(<MemoryGraph nodes={NODES} edges={EDGES} height={400} />);
    const btn = screen.getByRole("button", { name: /person/i });
    expect(btn.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("img", { name: /3 entities, 0 relations/ })).toBeTruthy();
  });

  it("clears focus with Escape and offers Clear focus while focused", () => {
    const onSelect = vi.fn();
    render(<MemoryGraph nodes={NODES} edges={EDGES} selectedId="a" onSelect={onSelect} height={400} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear focus" }));
    fireEvent.keyDown(screen.getByRole("img"), { key: "Escape" });
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });
});

describe("Schema and Ranked views", () => {
  it("shows derived types, relation kinds and the type pairs they connect", () => {
    render(<SchemaView schema={SCHEMA} />);
    expect(screen.getByRole("img", { name: /3 entity types/ })).toBeTruthy();
    expect(screen.getByText("Santhosh · Arjun")).toBeTruthy();
    const row = screen.getAllByText("works on").map((el) => el.closest("tr")).find(Boolean);
    expect(within(row).getByText("person")).toBeTruthy();
    expect(within(row).getByText("project")).toBeTruthy();
    expect(screen.getByText("↔ mutual")).toBeTruthy();
    expect(screen.getByText("one at a time")).toBeTruthy();
  });

  it("explains an empty schema", () => {
    render(<SchemaView schema={{ types: [], relations: [] }} />);
    expect(screen.getByText("No schema yet")).toBeTruthy();
  });

  it("lists entities by score with every component and picks on click", () => {
    const onPick = vi.fn();
    render(<RankedView data={RANKED} onPick={onPick} />);
    expect(screen.getByText(/0.45/)).toBeTruthy();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[1].textContent)).toEqual([
      expect.stringContaining("Santhosh"), expect.stringContaining("Arjun"), expect.stringContaining("Namma Agent")]);
    expect(within(rows[0]).getByTitle("Centrality: 100%")).toBeTruthy();
    expect(within(rows[2]).getByTitle("Recency: 50%")).toBeTruthy();
    fireEvent.click(rows[1]);
    expect(onPick).toHaveBeenCalledWith("a");
  });
});

describe("MemoryView", () => {
  function mountPage() {
    const calls = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
      const u = String(url);
      calls.push(u);
      if (u.startsWith("/api/memory/status")) return json({ connected: true, items: 9, entities: 5, relations: 5, since: null });
      if (u.startsWith("/api/memory/graph/schema")) return json(SCHEMA);
      if (u.startsWith("/api/memory/graph/ranked")) return json(RANKED);
      if (u.startsWith("/api/memory/graph/entity/k")) {
        return json({ ok: true, entity: { ...NODES[1], name: NODES[1].label },
                      edges: [{ id: "e1", rel: "studies_at", direction: "in", other: { id: "u", name: "Santhosh" }, support: 1, confidence: 0.7 }],
                      facts: [{ id: "f1", text: "Santhosh studies at KARE.", kind: "fact", created_at: new Date().toISOString() }],
                      rank: { score: 0.3 } });
      }
      if (u.startsWith("/api/memory/graph")) return json({ ok: true, nodes: NODES, edges: EDGES });
      if (u.startsWith("/api/memory/core")) return json({ ok: true, user: { entries: [], pct: 0 }, agent: { entries: [], pct: 0 } });
      if (u.startsWith("/api/memory/environment")) return json({ ok: true, environment: { os: "Windows" } });
      return json({ ok: true });
    });
    render(
      <MemoryRouter>
        <Routes>
          <Route element={<Outlet context={{ confirmAction: async () => true, dark: false }} />}>
            <Route path="/" element={<MemoryView />} />
          </Route>
        </Routes>
      </MemoryRouter>);
    return calls;
  }

  beforeEach(() => { localStorage.removeItem("namma-memory-tab"); });

  it("loads the graph and switches to working Schema and Ranked tabs", async () => {
    const calls = mountPage();
    await screen.findByTestId("memory-graph");
    fireEvent.click(screen.getByRole("tab", { name: "Schema" }));
    await screen.findByTestId("schema-view");
    expect(calls.some((u) => u.startsWith("/api/memory/graph/schema"))).toBe(true);
    fireEvent.click(screen.getByRole("tab", { name: "Ranked" }));
    await screen.findByTestId("ranked-view");
    expect(calls.some((u) => u.startsWith("/api/memory/graph/ranked"))).toBe(true);
    expect(localStorage.getItem("namma-memory-tab")).toBe("ranked");
  });

  it("finds an entity by alias, focuses it and shows its source facts", async () => {
    mountPage();
    await screen.findByTestId("memory-graph");
    fireEvent.change(screen.getByRole("searchbox", { name: "Find an entity" }), { target: { value: "kare" } });
    fireEvent.click(await screen.findByRole("button", { name: /Kalasalingam/ }));
    const panel = await screen.findByTestId("entity-panel");
    await within(panel).findByText("Santhosh studies at KARE.");
    expect(within(panel).getByText("studies at")).toBeTruthy();
    expect(within(panel).getByText("KARE")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "Close details" }));
    await waitFor(() => expect(screen.queryByTestId("entity-panel")).toBeNull());
  });
});
