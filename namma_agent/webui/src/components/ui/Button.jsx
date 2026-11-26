import { forwardRef } from "react";

// Phase 6 primitive: the one button. Variants map onto the semantic tokens;
// the global :focus-visible ring (index.css) covers keyboard focus.
const VARIANTS = {
  primary: "bg-accent text-accent-fg hover:opacity-90",
  secondary: "border border-border text-fg hover:bg-surface-sunken",
  ghost: "text-fg-muted hover:text-fg hover:bg-surface-sunken",
  danger: "bg-danger text-white hover:opacity-90",
  "danger-outline": "border border-danger/40 text-danger hover:bg-danger/10",
};
const SIZES = {
  sm: "h-8 px-2.5 text-sm rounded-md gap-1.5",
  md: "h-9 px-4 text-base rounded-lg gap-2",
};

const Button = forwardRef(function Button(
  { variant = "secondary", size = "md", className = "", type = "button", ...props }, ref) {
  return (
    <button ref={ref} type={type}
            className={`inline-flex items-center justify-center font-medium transition-colors duration-fast disabled:opacity-50 disabled:pointer-events-none ${VARIANTS[variant] || VARIANTS.secondary} ${SIZES[size] || SIZES.md} ${className}`}
            {...props} />
  );
});
export default Button;
