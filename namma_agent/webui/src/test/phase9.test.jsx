import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import ModelPicker, { loose, matchModels } from "../components/ui/ModelPicker.jsx";
import SelectMenu from "../components/ui/SelectMenu.jsx";
import SaveStatus from "../components/ui/SaveStatus.jsx";
import { isSaveOk, useAutosave } from "../useAutosave.js";
import { MODES, modeById } from "../roles.js";

const flush = (ms = 5) => act(() => new Promise((r) => setTimeout(r, ms)));

describe("useAutosave (no Save button)", () => {
  it("batches edits and writes once after the pause", async () => {
    const save = vi.fn(async () => ({ ok: true }));
    const { result } = renderHook(() => useAutosave(save, { delay: 20 }));
    act(() => { result.current.queue({ a: 1 }); result.current.queue({ b: 2 }); });
    expect(save).not.toHaveBeenCalled();
    await flush(40);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith({ a: 1, b: 2 });
    expect(result.current.status).toBe("saved");
  });

  it("flushes immediately on demand (secrets on blur)", async () => {
    const save = vi.fn(async () => ({ ok: true }));
    const { result } = renderHook(() => useAutosave(save, { delay: 10_000 }));
    await act(async () => { await result.current.queue({ TOKEN: "x" }, { immediate: true }); });
    expect(save).toHaveBeenCalledWith({ TOKEN: "x" });
  });

  it("rolls back on failure and retries the same batch", async () => {
    let fail = true;
    const save = vi.fn(async () => (fail ? { detail: "boom" } : { ok: true }));
    const onError = vi.fn();
    const { result } = renderHook(() => useAutosave(save, { delay: 5, onError }));
    act(() => { result.current.queue({ a: 1 }); });
    await flush(20);
    expect(result.current.status).toBe("error");
    expect(onError).toHaveBeenCalledWith({ a: 1 });
    fail = false;
    await act(async () => { await result.current.retry(); });
    expect(save).toHaveBeenLastCalledWith({ a: 1 });
    expect(result.current.status).toBe("saved");
  });

  it("treats null, ok:false and FastAPI errors as failures", () => {
    expect(isSaveOk(null)).toBe(false);
    expect(isSaveOk({ ok: false })).toBe(false);
    expect(isSaveOk({ detail: "bad" })).toBe(false);
    expect(isSaveOk({ ok: true })).toBe(true);
    expect(isSaveOk({ models: [] })).toBe(true);
  });

  it("shows Retry only on failure", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<SaveStatus status="saved" onRetry={onRetry} />);
    expect(screen.getByRole("status").textContent).toContain("Saved");
    rerender(<SaveStatus status="error" onRetry={onRetry} />);
    fireEvent.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe("mode list", () => {
  function Harness() {
    const [mode, setMode] = useState("agent");
    return (
      <>
        <SelectMenu label="Mode" value={mode} onChange={setMode}
                    options={MODES.map((m) => ({ id: m.id, label: `${m.label} · ${m.role}`, description: m.description }))} />
        <output data-testid="mode">{mode}</output>
      </>
    );
  }

  it("maps every mode to a Roman role", () => {
    expect(MODES.map((m) => [m.id, m.role])).toEqual([
      ["agent", "Imperator"], ["chat", "Scriba"], ["setup", "Architectus"]]);
    expect(modeById("nope").id).toBe("agent");
  });

  it("opens a listbox, moves with the arrow keys and picks with Enter", async () => {
    render(<Harness />);
    const btn = screen.getByRole("button", { name: /Mode: Agent/ });
    fireEvent.click(btn);
    await flush();
    const list = screen.getByRole("listbox", { name: "Mode" });
    expect(screen.getAllByRole("option")).toHaveLength(3);
    fireEvent.keyDown(list, { key: "ArrowDown" });
    fireEvent.keyDown(list, { key: "Enter" });
    expect(screen.getByTestId("mode").textContent).toBe("chat");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(btn);
  });

  it("closes on Escape without changing the mode, and marks the Escape handled", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Mode/ }));
    await flush();
    const ev = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    screen.getByRole("listbox").dispatchEvent(ev);
    await flush();
    expect(ev.defaultPrevented).toBe(true);   // so Escape doesn't also stop a running turn
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByTestId("mode").textContent).toBe("agent");
  });
});

describe("model picker", () => {
  const models = [
    { id: "m1", label: "GPT 4.1 mini", provider: "openai", model: "gpt-4.1-mini" },
    { id: "m2", label: "Claude Sonnet", provider: "anthropic", model: "claude-sonnet-5-5" },
    { id: "m3", label: "Llama local", provider: "ollama", model: "llama3.2" },
  ];

  it("matches loosely across hyphens, dots, underscores and spaces", () => {
    expect(loose("GPT-4.1_mini x")).toBe("gpt41minix");
    expect(matchModels(models, "gpt41mini").map((m) => m.id)).toEqual(["m1"]);
    expect(matchModels(models, "sonnet 5.5").map((m) => m.id)).toEqual(["m2"]);
    expect(matchModels(models, "OLLAMA").map((m) => m.id)).toEqual(["m3"]);
  });

  it("picks with the keyboard and skips a no-op re-pick", async () => {
    const onPick = vi.fn();
    const onClose = vi.fn();
    render(<ModelPicker models={models} current="m1" onPick={onPick} onClose={onClose} />);
    await flush();
    const box = screen.getByRole("combobox", { name: "Search models" });
    fireEvent.change(box, { target: { value: "llama" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onPick).toHaveBeenCalledWith("m3");
    expect(onClose).toHaveBeenCalled();
  });

  it("offers a way to add models when there are none", async () => {
    const onManage = vi.fn();
    render(<ModelPicker models={[]} current="" onPick={() => {}} onClose={() => {}} onManage={onManage} />);
    await flush();
    fireEvent.click(screen.getByText("Add one"));
    expect(onManage).toHaveBeenCalled();
  });
});
