// Phase 9 W1, slice 4: the side panel's Files/Preview, the profile rail, the
// model wizard on the W2 contract, Settings → Model / MCP, the Imperium theme,
// and the token migration.
import fs from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { collectChatFiles, fileKind } from "../chatFiles.js";
import RightPane, { RIGHT_PANE_TABS } from "../components/shell/RightPane.jsx";
import ProfileRail, { monogram, personaTone } from "../components/shell/ProfileRail.jsx";
import ModelWizard, { WIZARD_STEPS, looseMatch } from "../components/setup/ModelWizard.jsx";
import { normaliseProvider, setActiveModel, getActiveModel } from "../providerContract.js";
import { SETTINGS_TABS, tabForSlug } from "../settingsSections.js";
import { THEMES } from "../components/settings/AppearanceTab.jsx";
import { TAB_ICONS } from "../components/settings/icons.jsx";

const SRC = path.resolve(__dirname, "..");
const json = (body, ok = true) => Promise.resolve({
  ok, status: ok ? 200 : 404, headers: { get: () => "application/json" }, json: async () => body,
});
const html = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => "text/html" }, json: async () => ({}) });

afterEach(() => { vi.restoreAllMocks(); });

describe("side panel: Files and Preview", () => {
  const messages = [
    { id: 1, role: "user", content: "here", attachments: [{ name: "notes.pdf", path: "C:/up/notes.pdf" }] },
    { id: 2, role: "assistant", content: "Diagram: ![d](/api/media/diagrams/flow.png?v=2). Page /api/media/sims/orbit.html, and again /api/media/diagrams/flow.png." },
    { id: 3, role: "assistant", content: "Data at /api/media/out/report.csv." },
  ];

  it("collects attachments and every generated media file once, with kinds", () => {
    const files = collectChatFiles(messages);
    expect(files.map((f) => [f.name, f.kind, f.source])).toEqual([
      ["notes.pdf", "pdf", "attachment"],
      ["flow.png", "image", "generated"],
      ["orbit.html", "html", "generated"],
      ["report.csv", "text", "generated"],
    ]);
    expect(files[1].url).toBe("/api/media/diagrams/flow.png?v=2");
    expect(files[3].url).toBe("/api/media/out/report.csv");      // trailing full stop dropped
    expect(fileKind("x.MP4")).toBe("video");
    expect(fileKind("x.bin")).toBe("other");
  });

  it("lists files, previews an image, sandboxes HTML, and explains uploads", () => {
    render(<RightPane messages={messages} />);
    expect(RIGHT_PANE_TABS.map((t) => t.label)).toEqual(["Runs", "Plan", "Files", "Preview"]);
    fireEvent.click(screen.getByRole("tab", { name: /Files/ }));
    fireEvent.click(screen.getByRole("button", { name: /flow\.png/ }));
    expect(screen.getByRole("tab", { name: "Preview" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("img", { name: "flow.png" }).getAttribute("src")).toBe("/api/media/diagrams/flow.png?v=2");
    fireEvent.click(screen.getByRole("tab", { name: /Files/ }));
    fireEvent.click(screen.getByRole("button", { name: /orbit\.html/ }));
    const frame = document.querySelector("iframe[title='orbit.html']");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");        // never same-origin
    fireEvent.click(screen.getByRole("tab", { name: /Files/ }));
    fireEvent.click(screen.getByRole("button", { name: /notes\.pdf/ }));
    expect(screen.getByText(/isn't served to the browser/)).toBeTruthy();
  });
});

describe("profile rail", () => {
  it("shows one avatar per persona, rings the active one, and switches on click", async () => {
    let active = "core";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((url, opts) => {
      if (String(url).endsWith("/api/personas")) {
        return json({ active, personas: [{ id: "core", name: "Namma Agent" }, { id: "caesar", name: "Caesar" }] });
      }
      if (String(url).endsWith("/api/persona") && opts?.method === "POST") { active = JSON.parse(opts.body).id; return json({ ok: true }); }
      return json({});
    });
    const onManage = vi.fn();
    render(<ProfileRail onManage={onManage} />);
    const caesar = await screen.findByRole("radio", { name: "Persona: Caesar" });
    expect(screen.getByRole("radio", { name: "Persona: Namma Agent" }).getAttribute("aria-checked")).toBe("true");
    await act(async () => { fireEvent.click(caesar); });
    await waitFor(() => expect(caesar.getAttribute("aria-checked")).toBe("true"));
    const post = fetchMock.mock.calls.find(([u, o]) => String(u).endsWith("/api/persona") && o?.method === "POST");
    expect(JSON.parse(post[1].body)).toEqual({ id: "caesar" });
    fireEvent.click(screen.getByRole("button", { name: "Manage personas" }));
    expect(onManage).toHaveBeenCalled();
    expect(monogram("Marcus Aurelius")).toBe("MA");
    expect(monogram("Seneca")).toBe("SE");
    expect(personaTone("caesar")).toBe(personaTone("caesar"));
  });
});

describe("model wizard (W2 contract, today's fallbacks)", () => {
  it("normalises today's provider shape into the contract", () => {
    const p = normaliseProvider({ type: "openrouter", label: "OpenRouter (many models, one key)", key_env: "OPENROUTER_API_KEY", needs_key: true });
    expect(p).toMatchObject({ id: "openrouter", short: "OpenRouter", auth: "api_key", group: "Popular", connected: false });
    expect(normaliseProvider({ type: "ollama", needs_key: false, needs_base_url: true }).group).toBe("Local");
    expect(normaliseProvider({ id: "x", auth: "oauth", group: "Cloud" }).oauth).toBe(true);
    expect(looseMatch("llama-3.2-instruct", "llama32")).toBe(true);
  });

  it("walks provider → key → model → test → done", async () => {
    let keySaved = false;
    vi.spyOn(globalThis, "fetch").mockImplementation((url, opts) => {
      const u = String(url);
      if (u.endsWith("/api/providers")) {
        return json({ providers: [
          { type: "openai", label: "OpenAI", key_env: "OPENAI_API_KEY", needs_key: true, key_url: "https://k" },
          { type: "ollama", label: "Ollama (local)", needs_key: false, base_url: "http://127.0.0.1:11434/v1" },
        ] });
      }
      if (u.endsWith("/api/setup/secret")) { keySaved = true; return json({ ok: true }); }
      if (u.startsWith("/api/models")) return json({ models: ["gpt-4o-mini", "gpt-4.1"], source: "live" });
      if (u.endsWith("/api/setup/onboard")) {
        expect(JSON.parse(opts.body)).toMatchObject({ type: "openai", model: "gpt-4.1" });
        return json({ ok: true, ready: true, message: "OpenAI answered." });
      }
      return json({});
    });
    const onDone = vi.fn();
    render(<ModelWizard variant="onboarding" onDone={onDone} />);
    const wiz = screen.getByTestId("model-wizard");
    expect(wiz.dataset.step).toBe("Provider");
    expect(WIZARD_STEPS).toEqual(["Provider", "Sign in", "Model", "Test", "Done"]);
    fireEvent.click(await screen.findByRole("radio", { name: /OpenAI/ }));
    expect(wiz.dataset.step).toBe("Sign in");
    fireEvent.change(document.querySelector("[data-secret-input=OPENAI_API_KEY]"), { target: { value: "sk-test" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save" })); });
    await waitFor(() => expect(wiz.dataset.step).toBe("Model"));
    expect(keySaved).toBe(true);
    fireEvent.click(await screen.findByRole("option", { name: "gpt-4.1" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Connect & test" })); });
    await waitFor(() => expect(wiz.dataset.step).toBe("Done"));
    expect(screen.getByText("OpenAI answered.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start chatting" }));
    expect(onDone).toHaveBeenCalled();
  });

  it("filters providers by search and shows a failed test without advancing", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
      const u = String(url);
      if (u.endsWith("/api/providers")) return json({ providers: [{ type: "ollama", label: "Ollama (local)", needs_key: false }, { type: "groq", label: "Groq", needs_key: true }] });
      if (u.startsWith("/api/models")) return json({ models: ["all-minilm"], source: "live" });
      if (u.endsWith("/api/setup/onboard")) return json({ ok: false, message: "does not support chat" });
      return json({});
    });
    render(<ModelWizard />);
    fireEvent.change(await screen.findByRole("searchbox", { name: "Search providers" }), { target: { value: "olla" } });
    expect(screen.queryByRole("radio", { name: /Groq/ })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /Ollama/ }));
    await screen.findByRole("option", { name: "all-minilm" });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Connect & test" })); });
    expect(await screen.findByText(/does not support chat/)).toBeTruthy();
    expect(screen.getByTestId("model-wizard").dataset.step).toBe("Model");
  });

  it("uses W2's active_model when present, else moves the model to the top of models:", async () => {
    let saved = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((url, opts) => {
      const u = String(url);
      if (u.endsWith("/api/active_model")) return html();          // no W2 yet: SPA fallback
      if (u.endsWith("/api/configured_models") && opts?.method === "POST") { saved = JSON.parse(opts.body).models; return json({ ok: true }); }
      if (u.endsWith("/api/configured_models")) return json({ models: [{ id: "a" }, { id: "b" }] });
      return json({});
    });
    expect(await getActiveModel()).toBe("a");
    expect(await setActiveModel("b")).toEqual({ ok: true });
    expect(saved.map((m) => m.id)).toEqual(["b", "a"]);
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ model_id: "b", ok: true }));
    expect(await getActiveModel()).toBe("b");
    expect(await setActiveModel("b")).toEqual({ ok: true });
  });
});

describe("Settings: Model and MCP merged; split into sections", () => {
  it("has one Model tab and one MCP tab, and old links still land", () => {
    expect(SETTINGS_TABS).toContain("Model");
    expect(SETTINGS_TABS).toContain("MCP");
    for (const gone of ["Providers", "Models", "Config", "Servers"]) expect(SETTINGS_TABS).not.toContain(gone);
    expect(tabForSlug("providers")).toBe("Model");
    expect(tabForSlug("models")).toBe("Model");
    for (const t of SETTINGS_TABS) expect(TAB_ICONS[t]).toBeTruthy();   // every section has a Tabler icon
  });

  it("keeps Settings.jsx a shell; sections live in settings/", () => {
    const shell = fs.readFileSync(path.join(SRC, "components", "Settings.jsx"), "utf8");
    expect(shell.split("\n").length).toBeLessThan(260);
    for (const f of ["ModelTab", "McpTab", "BehaviorTab", "MessagingTab", "AppearanceTab", "SecurityTab", "MemoryTab", "PacksTab"]) {
      expect(fs.existsSync(path.join(SRC, "components", "settings", `${f}.jsx`))).toBe(true);
    }
  });
});

describe("Imperium theme", () => {
  const hex = (t) => t.split(/\s+/).map(Number);
  const lum = ([r, g, b]) => [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

  it("is a fifth named theme whose text meets 4.5:1 on every surface", () => {
    expect(THEMES.map((t) => t.id)).toEqual(["default", "slate", "classic", "mono", "imperium"]);
    const css = fs.readFileSync(path.join(SRC, "index.css"), "utf8");
    const block = css.slice(css.indexOf(".theme-imperium {"), css.indexOf("}", css.indexOf(".theme-imperium {")));
    const v = (n) => hex(block.match(new RegExp(`--${n}: ([\\d ]+);`))[1]);
    for (const surface of ["paper", "paper-soft", "paper-panel", "paper-sink"]) {
      expect(ratio(v("ink-faint"), v(surface))).toBeGreaterThanOrEqual(4.5);
    }
    for (const surface of ["night", "night-soft", "night-panel"]) {
      expect(ratio(v("night-faint"), v(surface))).toBeGreaterThanOrEqual(4.5);
    }
    expect(ratio([255, 255, 255], v("brand"))).toBeGreaterThanOrEqual(4.5);
    expect(css).toContain(".theme-imperium .font-serif");                 // Cinzel headings
    expect(css).toMatch(/:root, \.theme-default, \.theme-slate, \.theme-classic, \.theme-mono, \.theme-imperium \{/);
  });

  it("shows no laurel around the home mark (owner: remove it)", () => {
    expect(fs.existsSync(path.join(SRC, "components", "Laurel.jsx"))).toBe(false);
    const css = fs.readFileSync(path.join(SRC, "index.css"), "utf8");
    expect(css).not.toMatch(/\.laurel\b/);
  });
});

describe("token migration", () => {
  it("keeps legacy light/dark pairs below the post-migration ceiling", () => {
    let n = 0;
    const walk = (d) => fs.readdirSync(d).forEach((f) => {
      const p = path.join(d, f);
      if (fs.statSync(p).isDirectory()) { if (f !== "test") walk(p); }
      else if (/\.jsx?$/.test(f)) n += (fs.readFileSync(p, "utf8").match(/\bdark:/g) || []).length;
    });
    walk(SRC);
    expect(n).toBeLessThanOrEqual(100);     // 843 before Phase 9; the rest are one-off status tints
  });
});

describe("wizard groups follow the server (W2 catalogue)", () => {
  it("shows W2's groups in the server's order and never hides a provider", async () => {
    const { groupOrder } = await import("../providerContract.js");
    expect(groupOrder([{ group: "Odd" }], ["Popular", "Gateways"])).toEqual(["Popular", "Gateways", "Odd"]);
    expect(groupOrder([{ group: "Cloud" }], undefined)).toEqual(["Popular", "Aggregators", "Cloud", "Local"]);

    vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
      if (String(url).endsWith("/api/providers")) {
        return json({
          groups: ["Popular", "Subscriptions", "Gateways", "China", "Cloud", "Local"],
          providers: [
            { id: "openai", label: "OpenAI", group: "Popular", auth: "api_key" },
            { id: "copilot", label: "GitHub Copilot", group: "Subscriptions", auth: "oauth" },
            { id: "groq", label: "Groq", group: "Gateways", auth: "api_key" },
            { id: "kimi", label: "Kimi", group: "China", auth: "api_key" },
            { id: "ollama", label: "Ollama", group: "Local", auth: "none" },
          ],
        });
      }
      return json({});
    });
    render(<ModelWizard />);
    await screen.findByRole("radio", { name: /Kimi/ });
    const labels = screen.getAllByRole("radiogroup").map((g) => g.getAttribute("aria-label"));
    expect(labels).toEqual(["Popular providers", "Subscriptions providers", "Gateways providers", "China providers", "Local providers"]);
    for (const name of [/OpenAI/, /Copilot/, /Groq/, /Kimi/, /Ollama/]) expect(screen.getByRole("radio", { name })).toBeTruthy();
  });
});
