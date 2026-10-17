import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { lstat, readFile, realpath, writeFile } from 'node:fs/promises';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export interface FormatResult {
  checked: string[];
  formatted: string[];
}

interface PendingFormatting {
  path: string;
  name: string;
  original: string;
  formatted: string;
}

function readGitPaths(root: string, args: string[]): string[] {
  return execFileSync('git', args, { cwd: root, encoding: 'utf8' })
    .split('\0')
    .filter((path) => path.length > 0);
}

function findChangedFiles(root: string): string[] {
  const conflicts = readGitPaths(root, [
    'diff',
    '--name-only',
    '-z',
    '--diff-filter=U',
    '--',
    'frontend/',
  ]);
  if (conflicts.length > 0) {
    throw new Error(`Resolve frontend merge conflicts before formatting: ${conflicts.join(', ')}`);
  }

  const trackedFiles = readGitPaths(root, [
    'diff',
    'HEAD',
    '--name-only',
    '-z',
    '--diff-filter=ACMR',
    '--',
    'frontend/',
  ]);
  const untrackedFiles = readGitPaths(root, [
    'ls-files',
    '--others',
    '--exclude-standard',
    '-z',
    '--',
    'frontend/',
  ]);

  return [...new Set([...trackedFiles, ...untrackedFiles])].sort();
}

async function prepareFormatting(
  root: string,
  candidates: string[],
): Promise<{ checked: string[]; pending: PendingFormatting[] }> {
  const frontend = join(root, 'frontend');
  const prettier = await import('prettier');
  const checked: string[] = [];
  const pending: PendingFormatting[] = [];

  for (const name of candidates) {
    const path = resolve(root, name);
    const stat = await lstat(path).catch((error: unknown) => {
      if (error instanceof Error && 'code' in error && error.code === 'ENOENT') {
        return null;
      }
      throw error;
    });
    if (!stat?.isFile() || stat.isSymbolicLink()) {
      continue;
    }
    const resolved = await realpath(path);
    const withinFrontend = relative(frontend, resolved);
    if (isAbsolute(withinFrontend) || withinFrontend.startsWith('..')) {
      throw new Error(`Refusing to format a path outside frontend: ${name}`);
    }
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

async function writeFormatting(pending: PendingFormatting[]): Promise<string[]> {
  const formatted: string[] = [];
  for (const file of pending) {
    if ((await readFile(file.path, 'utf8')) !== file.original) {
      throw new Error(`File changed during formatting; retry after edits finish: ${file.name}`);
    }
    await writeFile(file.path, file.formatted);
    formatted.push(file.name);
  }
  return formatted;
}

export async function formatChangedFiles(root: string): Promise<FormatResult> {
  const candidates = findChangedFiles(root);
  if (candidates.length === 0) {
    return { checked: [], formatted: [] };
  }

  const { checked, pending } = await prepareFormatting(root, candidates);
  const formatted = await writeFormatting(pending);
  return { checked, formatted };
}

function readHookContinuation(): boolean {
  const event: unknown = JSON.parse(readFileSync(0, 'utf8'));
  if (
    typeof event !== 'object' ||
    event === null ||
    !('stop_hook_active' in event) ||
    typeof event.stop_hook_active !== 'boolean'
  ) {
    throw new Error('Expected boolean stop_hook_active in Codex Stop input.');
  }
  return event.stop_hook_active;
}

function reportHookSuccess(result: FormatResult, continued: boolean): void {
  if (result.formatted.length === 0) {
    process.stdout.write('{}');
    return;
  }

  const files = result.formatted.join(', ');
  if (continued) {
    process.stdout.write(
      JSON.stringify({
        systemMessage: `Prettier formatted: ${files}. Report these final formatting changes and any validation still needed.`,
      }),
    );
    return;
  }

  process.stdout.write(
    JSON.stringify({
      decision: 'block',
      reason: `Prettier formatted changed frontend files: ${files}. Review the formatting diff before completing. Do not undo formatting. Report any validation that needs rerunning after these edits.`,
    }),
  );
}

function reportFailure(error: unknown, hook: boolean, continued: boolean): void {
  const message = error instanceof Error ? error.message : String(error);
  if (!hook) {
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
    return;
  }

  const reason = `Changed-file formatting failed: ${message}. Fix the cause and rerun npm run format:changed in frontend. If blocked, report formatting as incomplete; do not claim validation passed.`;
  if (continued) {
    process.stdout.write(JSON.stringify({ systemMessage: reason }));
    return;
  }

  process.stdout.write(JSON.stringify({ decision: 'block', reason }));
}

async function main(): Promise<void> {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const hook = process.argv[2] === '--hook';
  let continued = false;

  try {
    if (process.argv.length > (hook ? 3 : 2)) {
      throw new Error('Usage: node scripts/format-changed.mts [--hook]');
    }
    if (hook) {
      continued = readHookContinuation();
    }
    const result = await formatChangedFiles(root);
    if (hook) {
      reportHookSuccess(result, continued);
    } else {
      process.stdout.write(
        `Checked ${result.checked.length} changed files; formatted ${result.formatted.length}.\n`,
      );
      for (const name of result.formatted) process.stdout.write(`${name}\n`);
    }
  } catch (error: unknown) {
    reportFailure(error, hook, continued);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
