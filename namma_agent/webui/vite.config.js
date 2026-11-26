import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "/" (absolute) so assets resolve correctly on *nested* client routes too.
// With "./" a hard refresh on /projects/:id requests /projects/assets/… which the
// SPA fallback answers with index.html (not JS) → blank page. The app is always
// served over HTTP by FastAPI (uvicorn), incl. inside the pywebview window, and
// /assets is a StaticFiles mount, so absolute paths are correct everywhere.
// The backend the dev server proxies to (NAMMA_API_PORT, default 8000) — lets a
// scratch backend on another port sit behind `npm run dev`.
const API = `127.0.0.1:${process.env.NAMMA_API_PORT || 8000}`;

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    port: 5173,
    proxy: {
      "/api": `http://${API}`,
      "/ws": { target: `ws://${API}`, ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
  // Phase 6: Vitest + React Testing Library smoke tests (npm test).
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{js,jsx}"],
    setupFiles: ["src/test/setup.js"],
  },
});
