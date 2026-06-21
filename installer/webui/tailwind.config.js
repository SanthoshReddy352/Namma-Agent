/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Clean, modern installer palette — soft paper + a confident blue accent
        // (echoing the reference design), with calm neutrals for chrome.
        canvas: { DEFAULT: "#f6f8fc", panel: "#ffffff", sink: "#eef1f7" },
        ink: { DEFAULT: "#10131a", soft: "#5a606e", faint: "#9aa0ad" },
        line: { DEFAULT: "#e6e9f0", soft: "#eff1f6" },
        brand: { DEFAULT: "#2f6bff", deep: "#1f4fd6", soft: "#e7eeff", wash: "#f1f5ff" },
        ok: { DEFAULT: "#1f9d57", soft: "#e6f6ee" },
        bad: { DEFAULT: "#d6453d", soft: "#fdecea" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
        display: ["Georgia", "ui-serif", "serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 10px 40px -18px rgba(20,30,60,0.25)",
        btn: "0 8px 20px -8px rgba(47,107,255,0.55)",
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        fade: { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        rise: "rise 0.28s ease-out",
        fade: "fade 0.4s ease-out",
      },
    },
  },
  plugins: [],
};
