import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import ConfirmDialog from "../components/ui/ConfirmDialog.jsx";
import Dialog, { isDialogOpen } from "../components/ui/Dialog.jsx";

const flush = () => act(() => new Promise((r) => setTimeout(r, 5)));

function Harness({ onClose }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open</button>
      {open && (
        <Dialog title="Edit" onClose={() => { onClose?.(); setOpen(false); }}>
          <input aria-label="Name" />
          <button type="button">Last</button>
        </Dialog>
      )}
    </>
  );
}

describe("Dialog", () => {
  it("has dialog semantics and closes on Escape, restoring focus", async () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const opener = screen.getByText("Open");
    opener.focus();
    fireEvent.click(opener);
    await flush();
    const dlg = screen.getByRole("dialog", { name: "Edit" });
    expect(dlg.getAttribute("aria-modal")).toBe("true");
    expect(isDialogOpen()).toBe(true);
    expect(document.activeElement).toBe(screen.getByLabelText("Name"));

    fireEvent.keyDown(document.activeElement, { key: "Escape" });
    await flush();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(isDialogOpen()).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("traps Tab focus inside the dialog", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("Open"));
    await flush();
    const first = screen.getByLabelText("Name");
    const last = screen.getByText("Last");
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });
});

describe("ConfirmDialog (BUG-12)", () => {
  it("focuses Cancel, not the destructive button", async () => {
    const onResolve = vi.fn();
    render(<ConfirmDialog message="Delete this chat?" onResolve={onResolve} />);
    await flush();
    expect(document.activeElement.textContent).toBe("Cancel");
    fireEvent.click(document.activeElement);
    expect(onResolve).toHaveBeenCalledWith(false);
  });

  it("confirms only on an explicit click and cancels on Escape", async () => {
    const onResolve = vi.fn();
    render(<ConfirmDialog message="Delete?" confirmLabel="Delete" onResolve={onResolve} />);
    await flush();
    fireEvent.keyDown(document.activeElement, { key: "Escape" });
    expect(onResolve).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByText("Delete"));
    expect(onResolve).toHaveBeenLastCalledWith(true);
  });
});
