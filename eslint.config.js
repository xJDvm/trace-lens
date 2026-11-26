// ESLint flat config: typescript-eslint recommended rules for the TypeScript sources.
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["**/dist/**", "**/node_modules/**", "backend/**"],
  },
  {
    files: ["**/*.{ts,tsx,js}"],
    extends: [...tseslint.configs.recommended],
  },
);
