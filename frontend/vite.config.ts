/// <reference types="vitest/config" />
import { defineConfig } from "vite";

// In development the frontend runs on :5173 and forwards /api/* to the
// FastAPI backend, so the browser sees a single origin (no CORS needed).
// Override the backend address with FRUIT_FLY_API_URL=http://host:port.
const api = process.env.FRUIT_FLY_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  server: {
    port: 5173,
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 1000, // three.js alone is ~600 kB
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
});