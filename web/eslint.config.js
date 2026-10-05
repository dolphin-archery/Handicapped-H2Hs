import js from "@eslint/js";
import prettier from "eslint-config-prettier/flat";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist", "public/py", "playwright-report", "test-results"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: { globals: globals.browser },
  },
  {
    // Fast Refresh rules apply to app code only.
    files: ["src/**/*.tsx"],
    extends: [reactRefresh.configs.vite],
  },
  {
    files: ["**/*.{js,mjs,cjs}"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  {
    // Config files, tests and end-to-end tests also run under Node.
    files: ["*.config.ts", "tests/**", "e2e/**"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
  prettier,
]);
