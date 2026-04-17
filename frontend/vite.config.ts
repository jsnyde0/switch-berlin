import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

// django-vite expects a manifest at STATIC_ROOT/dist/.vite/manifest.json
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/dist/",
  build: {
    outDir: resolve(__dirname, "../static/dist"),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: {
        app: resolve(__dirname, "src/app.css"),
        events: resolve(__dirname, "src/events/main.tsx"),
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    origin: "http://localhost:5173",
  },
});
