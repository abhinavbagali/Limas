import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";

const apiRoutes = ["/compare", "/compress", "/upload_pdf", "/index", "/retrieve", "/analytics", "/config", "/health"];
const apiTarget = process.env.LIMAS_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [
    tanstackStart({
      prerender: { enabled: true, crawlLinks: true, failOnError: true },
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": new URL("./src", import.meta.url).pathname,
    },
  },
  server: {
    host: "127.0.0.1",
    port: 3000,
    proxy: Object.fromEntries(apiRoutes.map((route) => [route, apiTarget])),
  },
});
