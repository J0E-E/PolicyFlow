/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite build configuration for the PolicyFlow SPA. The build emits static
// assets into dist/, which the multi-stage frontend Dockerfile copies into the
// nginx runtime image.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
