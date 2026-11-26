// Every Settings section must render (a missing import once blanked the whole
// window on Appearance). Each section is mounted with empty server replies;
// none may throw or trip the error boundary.
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Settings from "../components/Settings.jsx";
import { SETTINGS_TABS, sectionSlug } from "../settingsSections.js";

const reply = (url) => {
  const u = String(url);
  if (u.startsWith("/api/settings")) return { config: {}, env_set: {} };
  return {};
};

afterEach(() => vi.restoreAllMocks());

describe("Settings sections", () => {
  it.each(SETTINGS_TABS)("%s renders without crashing", async (tab) => {
    vi.spyOn(globalThis, "fetch").mockImplementation((url) => Promise.resolve({
      ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => reply(url), text: async () => "",
    }));
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    await act(async () => {
      render(<Settings section={sectionSlug(tab)} onClose={() => {}} theme="light" themeName="default"
                       onThemeToggle={() => {}} onThemeNameChange={() => {}} />);
    });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(err.mock.calls.filter((c) => String(c[0]).includes("render failed"))).toEqual([]);
  });
});
