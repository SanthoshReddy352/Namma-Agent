// Brand mark (Phase 9): the laurel-crowned statue chosen by the owner.
//
// Two forms:
//  - "plain"     — the engraving alone, as a single-colour mask in `--logo-ink`
//                  (what chat avatars use); in dark themes it sits on a small
//                  light coin (see index.css) so it never looks like noise;
//  - "medallion" — the highlighted mark: a round coin in the accent wash with
//                  a soft glow, the statue's silhouette filled in the surface
//                  colour (so the engraving no longer reads see-through) and
//                  the line work on top. Small sizes switch to a bolder line
//                  mask so the detail survives.
//  - `solid`     — the medallion on an opaque coin face with the bold engraving
//                  at any size (the home screen's large mark), instead of the
//                  translucent wash; reads cleanly on the painted background.
// `size` is the square box in px.
export default function Logo({ size = 28, className = "", title = "", variant = "plain", solid = false }) {
  const a11y = { role: title ? "img" : undefined, "aria-label": title || undefined, "aria-hidden": title ? undefined : true };
  if (variant !== "medallion") {
    // Light themes: just the engraving. Dark themes (CSS): the same engraving
    // on a light coin with the silhouette filled, so the fine hatching never
    // reads as loose bright pixels on a dark field.
    return (
      <span {...a11y} className={`brand-logo relative inline-block shrink-0 align-middle ${className}`}
            style={{ width: size, height: size }}>
        <span className="brand-logo-fill absolute inset-0" />
        <span className={`brand-logo-ink absolute inset-0 ${size <= 32 ? "brand-logo-bold" : ""}`} />
      </span>
    );
  }
  return (
    <span {...a11y} className={`brand-medallion ${solid ? "brand-medallion-solid" : ""} relative inline-block shrink-0 align-middle rounded-full ${className}`}
          style={{ width: size, height: size }}>
      <span className="brand-medallion-fill absolute inset-0" />
      <span className={`brand-medallion-ink absolute inset-0 ${size <= 40 || solid ? "brand-logo-bold" : ""}`} />
    </span>
  );
}
