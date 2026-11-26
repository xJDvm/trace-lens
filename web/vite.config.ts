import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** Address of the trace-lens API started by `python -m tracelens` (the default `HOST`/`PORT`). */
const API_TARGET = "http://127.0.0.1:4318";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": API_TARGET,
      "/v1": API_TARGET,
    },
  },
});
