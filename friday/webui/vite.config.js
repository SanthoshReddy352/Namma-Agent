import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "./" so the built bundle works when served from FastAPI StaticFiles
// or loaded as file:// inside the pywebview native window.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
