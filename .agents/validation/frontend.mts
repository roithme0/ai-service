import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  changedFiles,
  fingerprint as contentFingerprint,
  git,
  runCheck,
  sourcePath,
  writeFormatting,
  type FormatResult,
  type PendingFormatting,
  type ValidationPolicy,
  type ValidationProfile,
} from './shared.mts';

const changeInputs = ['frontend/', '.codex/', '.agents/validation/'];

export const frontendRequire = createRequire(
  new URL('../../frontend/package.json', import.meta.url),
);

const policy: ValidationPolicy = {
  label: 'Frontend',
  formatter: 'Prettier',
  success: 'Selected frontend checks passed.',
  retry: 'node .agents/validation/run.mts',
};

export function fingerprint(root: string): Promise<string> {
  return contentFingerprint(
    root,
    [...changeInputs, '.editorconfig'],
    ['frontend/node_modules/.package-lock.json'],
  );
}

export function frontendProfile(
  root: string,
): ValidationProfile {
  return {
    scope: 'frontend',
    policy,
    dependencies: (cache) => ({
      fingerprint: () => fingerprint(root),
      hasChanges: () =>
        git(root, ['status', '--porcelain', '-z', '--', ...changeInputs]).length > 0,
      format: () => formatFrontend(root),
      lint: () => lintFrontend(root, join(cache, 'lint.log')),
      test: () => Promise.resolve(),
    }),
  };
}

async function lintFrontend(root: string, logPath: string): Promise<void> {
  const frontend = join(root, 'frontend');
  await runCheck(
    frontend,
    'Frontend lint',
    [
      join(frontend, 'node_modules/eslint/bin/eslint.js'),
      '.',
      '../.agents/validation',
      '../.codex',
      '--max-warnings=0',
    ],
    logPath,
    120_000,
  );
}

async function prepareFormatting(
  root: string,
  candidates: string[],
): Promise<{ checked: string[]; pending: PendingFormatting[] }> {
  const frontend = join(root, 'frontend');
  const prettier = frontendRequire('prettier') as typeof import('prettier');
  const checked: string[] = [];
  const pending: PendingFormatting[] = [];

  for (const name of candidates) {
    const path = await sourcePath(root, 'frontend', name);
    if (!path) continue;
    const info = await prettier.getFileInfo(path, {
      ignorePath: [join(frontend, '.gitignore'), join(frontend, '.prettierignore')],
    });
    if (info.ignored || !info.inferredParser) {
      continue;
    }
    const options = await prettier.resolveConfig(path, { editorconfig: true });
    const original = await readFile(path, 'utf8');
    const formatted = await prettier.format(original, {
      ...options,
      filepath: path,
    });
    checked.push(name);
    if (original !== formatted) {
      pending.push({ path, name, original, formatted });
    }
  }

  return { checked, pending };
}

export async function formatFrontend(root: string): Promise<FormatResult> {
  const candidates = changedFiles(root, 'frontend/');
  if (candidates.length === 0) {
    return { checked: [], formatted: [] };
  }

  const { checked, pending } = await prepareFormatting(root, candidates);
  const formatted = await writeFormatting(pending);
  return { checked, formatted };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 3 || process.argv[2] !== '--format')
    throw new Error('Usage: node .agents/validation/frontend.mts --format');
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const result = await formatFrontend(root);
  process.stdout.write(
    `Checked ${result.checked.length} changed files; formatted ${result.formatted.length}.\n`,
  );
  for (const name of result.formatted) process.stdout.write(`${name}\n`);
}
