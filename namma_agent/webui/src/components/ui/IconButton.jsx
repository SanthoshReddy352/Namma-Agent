import { forwardRef } from "react";

// Phase 6 primitive: an icon-only button. `label` is REQUIRED — it becomes the
// accessible name (aria-label) and the tooltip. The hit target is ≥32px.
const IconButton = forwardRef(function IconButton(
  { label, className = "", type = "button", children, ...props }, ref) {
  if (!label && import.meta.env?.DEV) {
    console.error("IconButton needs a `label` (it is the button's accessible name).");
  }
  return (
    <button ref={ref} type={type} aria-label={label} title={label}
            className={`inline-grid place-items-center h-8 min-w-8 w-8 rounded-md text-fg-muted hover:text-fg hover:bg-surface-sunken transition-colors duration-fast disabled:opacity-50 ${className}`}
            {...props}>
      {children}
    </button>
  );
});
export default IconButton;
