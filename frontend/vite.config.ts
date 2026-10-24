import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// The redesigned panel is a second page served under /next/ while the old one
// stays at /. In dev, deep links such as /next/settings must load its page.
function nextPageFallback(): Plugin {
  return {
    name: "next-page-fallback",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url ?? "";
        if (url === "/next" || (url.startsWith("/next/") && !url.slice(6).includes("."))) {
          req.url = "/next/index.html";
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), nextPageFallback()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        next: resolve(__dirname, "next/index.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8080",
    },
  },
});
