import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only proxy so you can talk to FastAPI without configuring CORS.
// In production (static build), set VITE_API_BASE to your backend URL.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
