/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      // Phase 6 type scale: named sizes only (no arbitrary text-[Npx] in
      // components — a vitest guard enforces it). `prose` is the chat reading size.
      fontSize: {
        "2xs": "11px",
        xs: "12px",
        sm: "13px",
        base: "14px",
        prose: "15px",
        md: "16px",
        lg: "20px",
        xl: "24px",
      },
      borderRadius: { sm: "4px", md: "6px", lg: "10px" },
      zIndex: { base: "0", sticky: "10", dropdown: "20", overlay: "30", modal: "40", toast: "50", top: "100" },
      transitionDuration: { fast: "100ms", base: "150ms" },
      colors: {
        // Phase 6 semantic tokens: one set, redefined under .dark and per named
        // theme in src/index.css (no `dark:` duplicate needed). New code uses
        // these; the legacy paper/ink/night names below migrate over time.
        bg: "rgb(var(--bg) / <alpha-value>)",
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          raised: "rgb(var(--surface-raised) / <alpha-value>)",
          sunken: "rgb(var(--surface-sunken) / <alpha-value>)",
          hover: "rgb(var(--surface-hover) / <alpha-value>)",
          press: "rgb(var(--surface-press) / <alpha-value>)",
        },
        fg: {
          DEFAULT: "rgb(var(--fg) / <alpha-value>)",
          muted: "rgb(var(--fg-muted) / <alpha-value>)",
          subtle: "rgb(var(--fg-subtle) / <alpha-value>)",
          soft: "rgb(var(--fg-soft) / <alpha-value>)",
        },
        border: "rgb(var(--border) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          fg: "rgb(var(--accent-fg) / <alpha-value>)",
          wash: "rgb(var(--accent-wash) / <alpha-value>)",
        },
        danger: "rgb(var(--danger) / <alpha-value>)",
        warning: "rgb(var(--warning) / <alpha-value>)",
        success: "rgb(var(--success) / <alpha-value>)",
        focus: "rgb(var(--focus) / <alpha-value>)",
        // Color tokens resolve to CSS variables (RGB triplets) so multiple named
        // themes (Default / Slate / Classic / Mono) can re-skin the whole UI without
        // touching any component class. The values live in src/index.css; the
        // `<alpha-value>` placeholder keeps Tailwind's opacity utilities working.
        paper: {
          DEFAULT: "rgb(var(--paper) / <alpha-value>)",
          soft: "rgb(var(--paper-soft) / <alpha-value>)",
          panel: "rgb(var(--paper-panel) / <alpha-value>)",
          sink: "rgb(var(--paper-sink) / <alpha-value>)",
        },
        ink: {
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          soft: "rgb(var(--ink-soft) / <alpha-value>)",
          faint: "rgb(var(--ink-faint) / <alpha-value>)",
        },
        line: {
          DEFAULT: "rgb(var(--line) / <alpha-value>)",
          soft: "rgb(var(--line-soft) / <alpha-value>)",
        },
        brand: {
          DEFAULT: "rgb(var(--brand) / <alpha-value>)",
          soft: "rgb(var(--brand-soft) / <alpha-value>)",
          deep: "rgb(var(--brand-deep) / <alpha-value>)",
          wash: "rgb(var(--brand-wash) / <alpha-value>)",
        },
        night: {
          DEFAULT: "rgb(var(--night) / <alpha-value>)",
          soft: "rgb(var(--night-soft) / <alpha-value>)",
          panel: "rgb(var(--night-panel) / <alpha-value>)",
          line: "rgb(var(--night-line) / <alpha-value>)",
          ink: "rgb(var(--night-ink) / <alpha-value>)",
          faint: "rgb(var(--night-faint) / <alpha-value>)",
        },
      },
      fontFamily: {
        // System UI stack (Segoe UI Variable on Windows) — no web-font download.
        sans: ["Segoe UI Variable Text", "Segoe UI", "system-ui", "-apple-system", "Inter", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
        serif: ["Georgia", "ui-serif", "serif"],
      },
      boxShadow: {
        soft: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
        pop: "0 8px 30px -12px rgba(0,0,0,0.18)",
        // The one overlay elevation (menus, dialogs, palette) — paired with a hairline border.
        overlay: "0 12px 32px -8px rgb(0 0 0 / 0.22), 0 2px 6px rgb(0 0 0 / 0.08)",
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
      },
      animation: {
        rise: "rise 0.15s ease-out",
        blink: "blink 1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
