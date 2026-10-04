import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { buildPyBundle } from "./scripts/build-py-bundle.mjs";

// https://vite.dev/config/ and https://vitest.dev/config/
export default defineConfig(async () => {
  // Write the content-hashed Python bundle to public/py before Vite starts, so dev, build,
  // preview and tests all serve the current file, and compile its URL into the app.
  const pyBundle = await buildPyBundle();
  return {
    // Relative asset URLs: GitHub Pages serves the site under /<repo-name>/.
    base: "./",
    plugins: [react()],
    define: { __PY_BUNDLE__: JSON.stringify(pyBundle.url) },
    // The engine is a module worker that imports Pyodide's loader from the CDN at run time.
    worker: { format: "es" as const },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./tests/setup.ts"],
      include: ["tests/**/*.test.{ts,tsx}"],
    },
  };
});
