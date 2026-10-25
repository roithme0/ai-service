import { mkdir, mkdtemp, readFile, readdir } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  changedFiles,
  fingerprint,
  git,
  runCheck,
  sourcePath,
  writeFormatting,
  type FormatResult,
  type PendingFormatting,
  type ValidationProfile,
} from './shared.mts';

export function backendPython(root: string): string {
  return join(
    root,
    'backend/.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
  );
}

export async function backendFingerprint(root: string): Promise<string> {
  const backend = 'backend/';
  const libraries =
    process.platform === 'win32'
      ? ['backend/.venv/Lib/site-packages']
      : ['backend/.venv/lib/python3.13/site-packages'];
  const environment = ['backend/.venv/pyvenv.cfg', relative(root, backendPython(root))];
  for (const library of libraries) {
    const entries = await readdir(join(root, library), { withFileTypes: true }).catch(
      (error: unknown) => {
        if (error instanceof Error && 'code' in error && error.code === 'ENOENT') return [];
        throw error;
      },
    );
    for (const entry of entries) {
      if (entry.isDirectory() && entry.name.endsWith('.dist-info'))
        environment.push(join(library, entry.name, 'METADATA'));
    }
  }
  return fingerprint(root, [backend, '.codex/'], environment);
}

export async function formatBackend(
  root: string,
  cache: string,
  python: string = backendPython(root),
): Promise<FormatResult> {
  await mkdir(cache, { recursive: true });
  const pending: PendingFormatting[] = [];
  const checked: string[] = [];
  for (const name of changedFiles(root, 'backend/')) {
    if (
      !/\.pyi?$/.test(name) ||
      /\/(?:\.venv|\.codex-validation|__pycache__|\.pytest_cache[^/]*|\.pytest_tmp[^/]*)\//.test(
        name,
      )
    )
      continue;
    const path = await sourcePath(root, 'backend', name);
    if (!path) continue;
    const original = await readFile(path, 'utf8');
    const output = await runCheck(
      join(root, 'backend'),
      'Backend Black formatting',
      [
        '-X',
        'utf8',
        '-m',
        'black',
        '--config',
        join(root, 'backend/pyproject.toml'),
        '--quiet',
        '--stdin-filename',
        path,
        '-',
      ],
      join(cache, 'format.log'),
      120_000,
      python,
      original,
    );
    const newline = original.match(/\r?\n/)?.[0] ?? '\n';
    const formatted = output.replace(/\r?\n/g, newline);
    checked.push(name);
    if (original !== formatted) pending.push({ name, path, original, formatted });
  }
  return { checked, formatted: await writeFormatting(pending) };
}

export async function runBackendPytest(
  root: string,
  cache: string,
  python: string = backendPython(root),
): Promise<void> {
  await mkdir(cache, { recursive: true });
  const run = await mkdtemp(join(cache, 'pytest-'));
  await runCheck(
    join(root, 'backend'),
    'Backend pytest',
    ['-m', 'pytest', `--basetemp=${join(run, 'tmp')}`, '-o', `cache_dir=${join(run, 'cache')}`],
    join(cache, 'pytest.log'),
    300_000,
    python,
  );
}

export function backendProfile(root: string): ValidationProfile {
  return {
    scope: 'backend',
    policy: {
      label: 'Backend',
      formatter: 'Black',
      success: 'Shared hook tests and the full backend pytest suite passed.',
      retry:
        'backend validation: node .codex/validation/backend.mts --format, node --test .codex/validation/shared.test.mts .codex/validation/backend.test.mts from the repository root, then .venv/Scripts/python.exe -m pytest from backend (use .venv/bin/python on Unix)',
    },
    dependencies: (cache) => ({
      fingerprint: () => backendFingerprint(root),
      hasChanges: () =>
        git(root, ['status', '--porcelain', '-z', '--', 'backend/', '.codex/']).length > 0,
      format: () => formatBackend(root, cache),
      test: async () => {
        await runCheck(
          root,
          'Backend tooling tests',
          ['--test', '.codex/validation/backend.test.mts'],
          join(cache, 'tooling-tests.log'),
          120_000,
        );
        await runBackendPytest(root, cache);
      },
    }),
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 3 || process.argv[2] !== '--format')
    throw new Error('Usage: node .codex/validation/backend.mts --format');
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const result = await formatBackend(root, join(root, 'backend/.codex-validation/manual'));
  process.stdout.write(
    `Checked ${result.checked.length} changed Python files; formatted ${result.formatted.length}.\n`,
  );
  for (const name of result.formatted) process.stdout.write(`${name}\n`);
}
