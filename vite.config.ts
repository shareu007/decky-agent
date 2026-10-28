import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";

// Browser-only UI preview. These adapters are never included by the Decky build.
export default defineConfig({
  resolve: { alias: {
    "@decky/ui": fileURLToPath(new URL("./src/preview/ui.tsx", import.meta.url)),
    "@decky/api": fileURLToPath(new URL("./src/preview/api.ts", import.meta.url)),
  } },
  esbuild: { jsx: "automatic" },
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
});
