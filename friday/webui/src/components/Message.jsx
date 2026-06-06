export default function Message({ role, content, tools }) {
  const isUser = role === "user";
  const isError = role === "error";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} animate-rise`}>
      <div
        className={[
          "max-w-[78%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap",
          isUser
            ? "bg-glow text-white shadow-glow"
            : isError
            ? "bg-red-500/15 text-red-300 border border-red-500/30"
            : "glass text-ink-50",
        ].join(" ")}
      >
        {content || <span className="opacity-40">…</span>}
        {tools && tools.length > 0 && (
          <div className="mt-1.5 text-[11px] text-glow-soft/70">
            used: {tools.join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}
