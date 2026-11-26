// Brand mark (Phase 9): the laurel-crowned statue chosen by the owner.
//
// Two forms:
//  - "plain"     — the engraving alone, as a single-colour mask in `--logo-ink`
//                  (what chat avatars use);
//  - "medallion" — the highlighted mark: a round coin in the accent wash with
//                  a soft glow, the statue's silhouette filled in the surface
//                  colour (so the engraving no longer reads see-through) and
//                  the line work on top. Small sizes switch to a bolder line
//                  mask so the detail survives.
// `size` is the square box in px.
export default function Logo({ size = 28, className = "", title = "", variant = "plain" }) {
  const a11y = { role: title ? "img" : undefined, "aria-label": title || undefined, "aria-hidden": title ? undefined : true };
  if (variant !== "medallion") {
    return (
      <span {...a11y} className={`brand-logo ${size <= 32 ? "brand-logo-bold" : ""} inline-block shrink-0 align-middle ${className}`}
            style={{ width: size, height: size }} />
    );
  }
  return (
    <span {...a11y} className={`brand-medallion relative inline-block shrink-0 align-middle rounded-full ${className}`}
          style={{ width: size, height: size }}>
      <span className="brand-medallion-fill absolute inset-0" />
      <span className={`brand-medallion-ink absolute inset-0 ${size <= 40 ? "brand-logo-bold" : ""}`} />
    </span>
  );
}
