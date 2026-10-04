import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/tmf-api": "http://127.0.0.1:8000",
      "/agent": "http://127.0.0.1:8000",
      "/ops": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/knowledge": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
