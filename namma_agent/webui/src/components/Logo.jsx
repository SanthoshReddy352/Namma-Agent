// Brand mark (Phase 9): the laurel-crowned statue chosen by the owner, drawn
// from a single-colour mask (`/brand/logo-mask.png`) so its ink follows the
// theme — the original navy on light surfaces, a pale tint on dark ones
// (`--logo-ink` in index.css). `size` is the square box in px; the portrait
// art is centred inside it.
export default function Logo({ size = 28, className = "", title = "" }) {
  return (
    <span
      role={title ? "img" : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      className={`brand-logo inline-block shrink-0 align-middle ${className}`}
      style={{ width: size, height: size }}
    />
  );
}
