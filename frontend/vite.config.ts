import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// The redesigned panel is the root page. The previous one stays as a second
// page under /legacy/ for one release (switch-back safety net). In dev, deep
// links under /legacy/ must load that page instead of the root one.
function legacyPageFallback(): Plugin {
  return {
    name: "legacy-page-fallback",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url ?? "";
        if (url === "/legacy" || (url.startsWith("/legacy/") && !url.slice(8).includes("."))) {
          req.url = "/legacy/index.html";
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), legacyPageFallback()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        legacy: resolve(__dirname, "legacy/index.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8080",
    },
  },
});
