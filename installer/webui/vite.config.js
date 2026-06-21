import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "./" — the built UI is loaded from a file:// path inside pywebview (no HTTP
// server), so assets must resolve relative to index.html. There are no client-side
// routes here, so the absolute-path caveat that applies to the app's webui doesn't.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
});
