import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// `--mode single` produces one self-contained bundle that scripts/build-single.mjs inlines into a single HTML file.
export default defineConfig(({ mode }) => ({
  base: "./",
  plugins: [react()],
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 1500,
    ...(mode === "single" && {
      outDir: "dist-single",
      cssCodeSplit: false,
      assetsInlineLimit: Number.MAX_SAFE_INTEGER,
      rollupOptions: { output: { inlineDynamicImports: true } },
    }),
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
}));
