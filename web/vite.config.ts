import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The studio API (storyvid.api) runs on 8787; in dev, Vite proxies to it.
const API = "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5288,
    strictPort: true,
    proxy: { "/api": API, "/media": API },
  },
});
