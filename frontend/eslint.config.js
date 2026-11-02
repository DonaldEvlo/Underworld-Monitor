// Flat config ESLint 9 (l'ancien format .eslintrc n'est plus supporte depuis v9).
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "*.tsbuildinfo"] },
  {
    // ⚠️ `recommendedTypeChecked` et non `recommended` : sans le typage, les
    // regles qui comptent ici ne tournent pas du tout. Mesure du 2026-09-04 --
    // l'activer a revele **70 problemes** invisibles jusque-la, dont 48
    // handlers async passes a un attribut JSX (une erreur y devenait un rejet
    // NON TRAITE, sans retour a l'analyste), 4 promesses non traitees, et une
    // douzaine d'`any` venant de `response.json()` au coeur du client HTTP --
    // invisibles au grep, parce qu'ils viennent de la plateforme et non d'un
    // `any` ecrit a la main.
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      // Le typage exige de designer le projet TypeScript : sans lui, les
      // regles type-aware sont silencieusement inertes.
      parserOptions: {
        project: "./tsconfig.json",
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      // Le prefixe "_" marque un argument volontairement inutilise (aligne sur
      // noUnusedParameters de tsconfig.json).
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  // Fichiers de config outillage : contexte Node, hors du perimetre navigateur.
  //
  // ⚠️ Hors du lint type-aware : ils ne figurent pas dans `tsconfig.json`
  // (dont `include` vaut `src`), le parser n'a donc aucun programme
  // TypeScript ou les rattacher.
  {
    files: ["*.config.js"],
    languageOptions: { globals: globals.node },
  },
  // ⚠️ Fichiers TypeScript hors `src` (donc hors `tsconfig.json`) : ils ont
  // besoin du parser TypeScript mais PAS de `parserOptions.project` -- ils
  // n'appartiennent à aucun programme, le parser échouerait.
  {
    files: ["*.config.ts"],
    extends: [...tseslint.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  // Scripts de diagnostic (Playwright) : hors du projet TypeScript, donc hors
  // du lint type-aware -- ils ne sont pas embarques dans l'application.
  {
    files: ["scripts/**", "demo/**"],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: { globals: globals.node },
  },
);
