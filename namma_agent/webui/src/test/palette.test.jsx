import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CommandPalette, { matchCommands } from "../components/ui/CommandPalette.jsx";
import { sectionSlug, settingsPath, tabForSlug } from "../settingsSections.js";

const flush = () => act(() => new Promise((r) => setTimeout(r, 5)));

describe("command palette", () => {
  const make = () => [
    { id: "new", group: "Chat", label: "New chat", run: vi.fn() },
    { id: "s-providers", group: "Settings", label: "Settings: Providers", keywords: "intelligence", run: vi.fn() },
    { id: "s-servers", group: "Settings", label: "Settings: Servers", keywords: "mcp", run: vi.fn() },
  ];

  it("matches every typed word against label, group and keywords", () => {
    const cmds = make();
    expect(matchCommands(cmds, "").length).toBe(3);
    expect(matchCommands(cmds, "settings mcp").map((c) => c.id)).toEqual(["s-servers"]);
    expect(matchCommands(cmds, "PROV")).toHaveLength(1);
  });

  it("filters, moves with the arrow keys and runs on Enter", async () => {
    const cmds = make();
    const onClose = vi.fn();
    render(<CommandPalette commands={cmds} onClose={onClose} />);
    await flush();
    const input = screen.getByRole("combobox", { name: "Search commands" });
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: "settings" } });
    expect(screen.getAllByRole("option")).toHaveLength(2);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onClose).toHaveBeenCalled();
    await flush();
    expect(cmds[2].run).toHaveBeenCalledTimes(1);
    expect(cmds[1].run).not.toHaveBeenCalled();
  });

  it("closes on Escape without running anything", async () => {
    const cmds = make();
    const onClose = vi.fn();
    render(<CommandPalette commands={cmds} onClose={onClose} />);
    await flush();
    fireEvent.keyDown(document.activeElement, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
    cmds.forEach((c) => expect(c.run).not.toHaveBeenCalled());
  });
});

describe("settings deep links", () => {
  it("maps sections to /settings/<slug> and back", () => {
    expect(settingsPath("Providers")).toBe("/settings/providers");
    expect(settingsPath()).toBe("/settings/behavior");
    expect(tabForSlug("mcp")).toBe("MCP");
    // The merged MCP tab answers the old Config / Servers links.
    expect(tabForSlug("servers")).toBe("MCP");
    expect(tabForSlug("SERVERS")).toBe("MCP");
    expect(tabForSlug("config")).toBe("MCP");
    expect(tabForSlug("nope")).toBeNull();
    expect(sectionSlug("Checkpoints")).toBe("checkpoints");
  });
});
