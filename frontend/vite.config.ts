import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.RETURNFLOW_API_ORIGIN ?? "http://127.0.0.1:8000",
      "/health": process.env.RETURNFLOW_API_ORIGIN ?? "http://127.0.0.1:8000",
      "/ready": process.env.RETURNFLOW_API_ORIGIN ?? "http://127.0.0.1:8000",
    },
  },
});

