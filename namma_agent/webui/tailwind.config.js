/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
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
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
        serif: ["Georgia", "ui-serif", "serif"],
      },
      boxShadow: {
        soft: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
        pop: "0 8px 30px -12px rgba(0,0,0,0.18)",
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
      },
      animation: {
        rise: "rise 0.22s ease-out",
        blink: "blink 1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
