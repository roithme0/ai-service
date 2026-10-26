import { createRequire } from 'node:module';
import { dirname } from 'node:path';
import { fileURLToPath, URL } from 'node:url';

const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const eslint = require('@eslint/js');
const { defineConfig } = require('eslint/config');
const tseslint = require('typescript-eslint');

export default defineConfig(
  { files: ['**/*.mjs'], extends: [eslint.configs.recommended] },
  {
    files: ['**/*.mts'],
    extends: [eslint.configs.recommended, tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        project: './tsconfig.json',
        tsconfigRootDir: dirname(fileURLToPath(import.meta.url)),
      },
    },
  },
);
