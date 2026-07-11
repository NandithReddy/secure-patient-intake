import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Forward /api/* to the FastAPI service. With this proxy in place the
      // frontend needs no VITE_API_URL in development, and the browser makes
      // same-origin requests, so CORS never enters the picture.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Recharts + framer-motion dominate the bundle. Splitting them keeps
        // the app chunk small enough to parse quickly on a cold load.
        manualChunks: {
          charts: ["recharts"],
          motion: ["framer-motion"],
        },
      },
    },
  },
});
