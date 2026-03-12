import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev convenience:
// - If FastAPI runs on :8000 and Vite runs on :5173, proxy API calls.
// - In production, serve the built files with Nginx and proxy /buyer/* to FastAPI.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/buyer": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/static": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
