// ESLint for the browser code (TEST-007). no-unsanitized flags innerHTML /
// insertAdjacentHTML / document.write with non-constant input - the XSS sinks
// that matter most in a browser-crypto app.
import js from "@eslint/js";
import nounsanitized from "eslint-plugin-no-unsanitized";
import globals from "globals";

export default [
  { ignores: ["frontend/static/js/vendor/**", "tests/js/fixtures/**", "node_modules/**", ".venv/**"] },
  js.configs.recommended,
  nounsanitized.configs.recommended,
  {
    files: ["frontend/static/js/**/*.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: { ...globals.browser } },
    rules: { "no-unused-vars": ["warn", { args: "none", caughtErrors: "none" }], "no-empty": ["error", { allowEmptyCatch: true }] },
  },
  {
    files: ["frontend/static/js/sw.js"],
    languageOptions: { globals: { ...globals.serviceworker } },
  },
  {
    files: ["tests/js/**/*.mjs"],
    languageOptions: { ecmaVersion: 2022, sourceType: "module", globals: { ...globals.node } },
  },
];
