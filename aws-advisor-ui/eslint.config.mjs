import tseslint from "typescript-eslint";

const eslintConfig = [
  ...tseslint.configs.recommended,
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "coverage/**",
      "results-screenshots/**",
      "next-env.d.ts",
    ],
  },
];

export default eslintConfig;
