import js from "@eslint/js";
import security from "eslint-plugin-security";

export default [
  js.configs.recommended,
  security.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "commonjs",
      globals: {
        require: "readonly", module: "writable", exports: "writable", console: "readonly",
        process: "readonly", __dirname: "readonly", setTimeout: "readonly", Buffer: "readonly",
      },
    },
    rules: {
      eqeqeq: "error",
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-var": "warn",
      "prefer-const": "warn",
      // Too noisy on ordinary array indexing; would create false positives on clean code.
      "security/detect-object-injection": "off",
    },
  },
];
