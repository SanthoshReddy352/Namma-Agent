import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createTokenBatcher } from "../tokenBatcher.js";

// Count markdown renders per source text: the memoised transcript must not
// re-render (re-parse) earlier messages while the last one streams.
const renders = new Map();
vi.mock("../components/Markdown.jsx", () => ({
  default: ({ children }) => {
    renders.set(children, (renders.get(children) || 0) + 1);
    return <div data-testid="md">{children}</div>;
  },
}));

const { default: Message } = await import("../components/Message.jsx");
const { StepList } = await import("../components/Activity.jsx");
const { default: Composer } = await import("../components/Composer.jsx");

function Transcript({ messages }) {
  return <div>{messages.map((m) => <Message key={m.id} {...m} />)}</div>;
}

describe("streaming performance", () => {
  it("does not re-render earlier messages when a reply streams", () => {
    renders.clear();
    const earlier = [
      { id: 1, role: "user", content: "hi" },
      { id: 2, role: "assistant", content: "First answer, long and settled." },
      { id: 3, role: "user", content: "again" },
    ];
    let streaming = { id: 4, role: "assistant", content: "Tok" };
    const { rerender } = render(<Transcript messages={[...earlier, streaming]} />);
    for (let i = 0; i < 200; i++) {
      streaming = { ...streaming, content: streaming.content + " tok" };
      rerender(<Transcript messages={[...earlier, streaming]} />);
    }
    expect(renders.get("First answer, long and settled.")).toBe(1);
    expect(screen.getAllByTestId("md").at(-1).textContent).toBe(streaming.content);
  });
});

describe("token batcher", () => {
  it("coalesces tokens per session and flushes in order", () => {
    const calls = [];
    let pending = null;
    const timers = { set: (fn) => { pending = fn; return 1; }, clear: () => { pending = null; } };
    const b = createTokenBatcher((k, t) => calls.push([k, t]), 50, timers);
    b.push("a", "Hel"); b.push("a", "lo"); b.push("b", "x"); b.push("a", "!");
    expect(calls).toEqual([]);
    pending();
    expect(calls).toEqual([["a", "Hello!"], ["b", "x"]]);
    b.push("a", "more");
    b.flush();               // another event arrived: flush synchronously
    expect(calls.at(-1)).toEqual(["a", "more"]);
    expect(b.size).toBe(0);
  });

  it("flushes on its own with the default (real) timers", async () => {
    // Regression: the defaults once passed bare setTimeout as a method, which
    // browsers reject ("Illegal invocation"), so nothing streamed live.
    const setSpy = vi.spyOn(globalThis, "setTimeout");
    const calls = [];
    const b = createTokenBatcher((k, t) => calls.push([k, t]), 10);
    b.push("s", "a"); b.push("s", "b");
    expect(setSpy.mock.contexts.at(-1)).not.toEqual(expect.objectContaining({ set: expect.anything() }));
    setSpy.mockRestore();
    await new Promise((r) => setTimeout(r, 30));
    expect(calls).toEqual([["s", "ab"]]);
  });
});

describe("smoke: send and approve", () => {
  it("sends the typed prompt on Enter", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} onStop={() => {}} busy={false} mode="agent" setMode={() => {}} />);
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "hello there" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("hello there", []);
  });

  it("approves a pending tool once from the inline card", () => {
    const onApprove = vi.fn();
    render(<StepList items={[{ kind: "approval", id: 7, tool: "run_shell", args: { command: "ls" } }]} onApprove={onApprove} />);
    fireEvent.click(screen.getByText("Allow once"));
    expect(onApprove).toHaveBeenCalledWith(7, true, "once");
  });
});
