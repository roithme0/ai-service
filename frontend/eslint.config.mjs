import eslint from '@eslint/js';
import { defineConfig, globalIgnores } from 'eslint/config';
import angular from 'angular-eslint';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

export default defineConfig(
  globalIgnores([
    '**/node_modules/**',
    '**/.angular/**',
    '**/.codex-validation/**',
    'dist/**',
    'out-tsc/**',
    'coverage/**',
    'projects/chat-ui/conversation/generated/**',
  ]),
  {
    files: ['**/*.{js,cjs,mjs}'],
    extends: [eslint.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['**/*.{ts,mts,cts}'],
    extends: [
      eslint.configs.recommended,
      tseslint.configs.recommendedTypeChecked,
      angular.configs.tsRecommended,
    ],
    languageOptions: {
      parserOptions: {
        project: './tsconfig.eslint.json',
        tsconfigRootDir: dirname(fileURLToPath(import.meta.url)),
      },
    },
    processor: angular.processInlineTemplates,
  },
  {
    files: ['**/*.html'],
    extends: [angular.configs.templateRecommended, angular.configs.templateAccessibility],
  },
);
