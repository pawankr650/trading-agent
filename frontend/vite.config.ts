import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` -> http://localhost:5173 with /api proxied to the FastAPI backend (python -m server.app)
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": process.env.API_URL ?? "http://127.0.0.1:8000" } },
  build: { outDir: "dist", emptyOutDir: true },
});
