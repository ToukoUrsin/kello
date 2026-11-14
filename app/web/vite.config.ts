import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // KELLO_API: point the dev server at another local API (for example a second copy on another port).
  server: { port: 5174, proxy: { "/api": process.env.KELLO_API || "http://127.0.0.1:8742" } },
  build: { outDir: "dist", sourcemap: false },
});
