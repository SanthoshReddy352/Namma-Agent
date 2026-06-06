/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: { 900: "#0a0b10", 800: "#0f111a", 700: "#161924", 600: "#1e2230" },
        glow: { DEFAULT: "#5b8cff", soft: "#7aa2ff" },
        accent: "#22d3ee",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        glow: "0 0 40px -10px rgba(91,140,255,0.5)",
      },
      keyframes: {
        pulseRing: {
          "0%,100%": { transform: "scale(1)", opacity: "0.7" },
          "50%": { transform: "scale(1.15)", opacity: "0.3" },
        },
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
      animation: {
        pulseRing: "pulseRing 2s ease-in-out infinite",
        rise: "rise 0.25s ease-out",
      },
    },
  },
  plugins: [],
};
