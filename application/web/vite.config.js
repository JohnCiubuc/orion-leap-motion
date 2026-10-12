import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Build straight into the Python package so the server ships the UI.
export default defineConfig({
  plugins: [svelte()],
  base: "./",
  build: { outDir: "../orion/web", emptyOutDir: true, chunkSizeWarningLimit: 900 },
});
