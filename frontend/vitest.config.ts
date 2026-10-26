import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/next/test/setup.ts"],
    // Whole-page tests (the editor) take several seconds when the suite runs in parallel.
    testTimeout: 15_000,
  },
});
