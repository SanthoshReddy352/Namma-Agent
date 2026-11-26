// Update progress (Phase 9 W3): "Update now" in the desktop app must show what's
// happening (download %, then the install step), never a silent wait.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ checkUpdate: vi.fn(), applyUpdate: vi.fn() }));
vi.mock("../api.js", () => api);

import UpdateBanner from "../components/UpdateBanner.jsx";
import { describeUpdate, followUpdate } from "../updateProgress.js";

beforeEach(() => { localStorage.clear(); api.checkUpdate.mockReset(); api.applyUpdate.mockReset(); });
afterEach(() => { vi.useRealTimers(); });

describe("describeUpdate", () => {
  it("reports download percentage, the install step and failures", () => {
    expect(describeUpdate({ status: "downloading", progress: 41.6, latest: "2.4.0" }))
      .toMatchObject({ pct: 42, busy: true, label: "Downloading Namma Agent 2.4.0… 42%" });
    expect(describeUpdate({ status: "installing", latest: "2.4.0" }).label).toMatch(/Installing Namma Agent 2\.4\.0.*reopens/);
    expect(describeUpdate({ status: "ready", latest: "2.4.0" }).pct).toBe(100);
    expect(describeUpdate({ status: "error", error: "disk full" })).toMatchObject({ failed: true, label: "The update failed: disk full" });
    expect(describeUpdate({ status: "available", latest: "2.4.0" }).label).toBe("Starting the update to 2.4.0…");
  });
});

describe("followUpdate", () => {
  it("polls until stopped and keeps going through a backend restart", async () => {
    vi.useFakeTimers();
    const seen = [];
    const answers = [{ status: "downloading", progress: 10 }, null, { status: "installing" }];
    const check = vi.fn(async () => { const a = answers.shift(); if (a === null) throw new Error("down"); return a; });
    const stop = followUpdate((s) => seen.push(s.status), { interval: 100, check });
    await vi.advanceTimersByTimeAsync(350);
    stop();
    expect(seen).toEqual(["downloading", "installing"]);
    const calls = check.mock.calls.length;
    await vi.advanceTimersByTimeAsync(500);
    expect(check.mock.calls.length).toBe(calls);
  });

  it("stops on an error", async () => {
    vi.useFakeTimers();
    const check = vi.fn(async () => ({ status: "error", error: "x" }));
    followUpdate(() => {}, { interval: 100, check });
    await vi.advanceTimersByTimeAsync(500);
    expect(check).toHaveBeenCalledTimes(1);
  });
});

describe("UpdateBanner (desktop app)", () => {
  it("shows the download percentage and then the install step after Update now", async () => {
    vi.useFakeTimers();
    api.checkUpdate.mockResolvedValueOnce({ update_available: true, latest: "2.4.0", current: "2.3.2",
      status: "available", managed_by: "desktop" });
    api.applyUpdate.mockResolvedValue({ started: true, managed_by: "desktop" });
    render(<UpdateBanner />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText("Update available")).toBeTruthy();

    api.checkUpdate.mockResolvedValueOnce({ update_available: true, latest: "2.4.0", status: "downloading", progress: 42, managed_by: "desktop" });
    await act(async () => { fireEvent.click(screen.getByText("Update now")); await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText("Downloading Namma Agent 2.4.0… 42%")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("42");

    api.checkUpdate.mockResolvedValue({ update_available: true, latest: "2.4.0", status: "installing", managed_by: "desktop" });
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    expect(screen.getByText(/Installing Namma Agent 2\.4\.0/)).toBeTruthy();
  });

  it("picks up an update already under way (started from the tray)", async () => {
    vi.useFakeTimers();
    api.checkUpdate.mockResolvedValue({ update_available: true, latest: "2.4.0", status: "downloading", progress: 7, managed_by: "desktop" });
    render(<UpdateBanner />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText("Downloading Namma Agent 2.4.0… 7%")).toBeTruthy();
  });
});
