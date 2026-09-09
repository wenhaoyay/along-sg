import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import stylistic from "@stylistic/eslint-plugin";
import prettier from "eslint-config-prettier/flat";

export default defineConfig([
  ...nextVitals,
  ...nextTs,

  // Prettier owns formatting, so this switches off every core rule that would
  // disagree with it. It has to come after the configs it is disabling rules
  // from.
  prettier,

  {
    plugins: { "@stylistic": stylistic },
    rules: {
      // Prettier's printWidth is a target, not a ceiling: it cannot break a
      // long string, a URL or a comment, so those sail past 100 columns
      // silently. This rule is what actually holds the line - hence the
      // exemptions for exactly the cases Prettier is unable to fix, which are
      // reformatted by hand or left deliberately long.
      "@stylistic/max-len": [
        "error",
        {
          code: 100,
          tabWidth: 2,
          ignoreUrls: true,
          ignoreRegExpLiterals: true,
          // A test fixture or an inline data URI is one token; wrapping it
          // would mean inventing a variable to hold a fragment of it.
          ignoreStrings: true,
          ignoreTemplateLiterals: true,
        },
      ],
    },
  },

  globalIgnores([".next/**", "out/**", "next-env.d.ts", "test-results/**"]),
]);
