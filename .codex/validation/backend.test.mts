import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rename, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { backendFingerprint, backendPython, formatBackend } from './backend.mts';

const repository = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const python = backendPython(repository);

function git(root: string, args: string[]): string {
  return execFileSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true });
}

async function fixture(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-backend-hooks-'));
  await mkdir(join(root, 'backend'), { recursive: true });
  await writeFile(
    join(root, 'backend/.gitignore'),
    '.venv/\n.codex-validation/\n__pycache__/\ntests/.pytest_cache*/\ntests/.pytest_tmp*/\n',
  );
  await writeFile(
    join(root, 'backend/pyproject.toml'),
    await readFile(join(repository, 'backend/pyproject.toml')),
  );
  git(root, ['init', '-q']);
  git(root, ['config', 'user.name', 'Hook test']);
  git(root, ['config', 'user.email', 'hook@example.invalid']);
  git(root, ['config', 'core.autocrlf', 'false']);
  await writeFile(join(root, 'backend/source.py'), 'value=  1\n');
  git(root, ['add', '.']);
  git(root, ['commit', '-qm', 'Fixture']);
  return root;
}

function format(root: string): ReturnType<typeof formatBackend> {
  return formatBackend(root, join(root, 'backend/.codex-validation/manual'), python);
}

void test('Black formats staged, unstaged, renamed and untracked Python files without changing the index', async () => {
  const root = await fixture();
  await writeFile(join(root, 'backend/staged.py'), 'value=  2\n');
  git(root, ['add', 'backend/staged.py']);
  const index = git(root, ['show', ':backend/staged.py']);
  await writeFile(join(root, 'backend/staged.py'), 'value=  3\n');
  await writeFile(join(root, 'backend/new file.py'), 'value=  4\n');
  const first = await format(root);
  assert.deepEqual(first.formatted, ['backend/new file.py', 'backend/staged.py']);
  assert.equal(await readFile(join(root, 'backend/source.py'), 'utf8'), 'value=  1\n');
  assert.equal(git(root, ['show', ':backend/staged.py']), index);
  assert.equal(await readFile(join(root, 'backend/staged.py'), 'utf8'), 'value = 3\n');
  git(root, ['mv', 'backend/source.py', 'backend/renamed.py']);
  assert.deepEqual((await format(root)).formatted, ['backend/renamed.py']);
  assert.deepEqual((await format(root)).formatted, []);
});

void test('Black skips ignored caches, non-Python and deleted files', async () => {
  const root = await fixture();
  await rename(join(root, 'backend/source.py'), join(root, 'source.py'));
  for (const name of [
    'backend/.venv/generated.py',
    'backend/tests/.pytest_tmp/test.py',
    'backend/tests/.pytest_tmp_old/test.py',
    'backend/__pycache__/bad.py',
    'frontend/file.py',
    'backend/readme.md',
  ]) {
    await mkdir(dirname(join(root, name)), { recursive: true });
    await writeFile(join(root, name), 'invalid python !');
  }
  assert.deepEqual(await format(root), { checked: [], formatted: [] });
});

void test('Black parse failures leave all candidate files untouched', async () => {
  const root = await fixture();
  await writeFile(join(root, 'backend/a.py'), 'value=  2\n');
  await writeFile(join(root, 'backend/z.py'), 'def invalid(\n');
  await assert.rejects(format(root), /Backend Black formatting failed/);
  assert.equal(await readFile(join(root, 'backend/a.py'), 'utf8'), 'value=  2\n');
});

void test('Black preserves Unicode, line endings, and explicitly excluded source files', async () => {
  const root = await fixture();
  const config = join(root, 'backend/pyproject.toml');
  await writeFile(
    config,
    (await readFile(config, 'utf8')).replace(
      '[tool.black]',
      '[tool.black]\nforce-exclude = "excluded.py"',
    ),
  );
  await writeFile(join(root, 'backend/lf.py'), 'value=  "Grüße 日本語"\n');
  await writeFile(join(root, 'backend/crlf.py'), 'value=  "Grüße 日本語"\r\n');
  await writeFile(join(root, 'backend/excluded.py'), 'value=  "Grüße 日本語"\n');
  assert.deepEqual((await format(root)).formatted, ['backend/crlf.py', 'backend/lf.py']);
  assert.equal(await readFile(join(root, 'backend/lf.py'), 'utf8'), 'value = "Grüße 日本語"\n');
  assert.equal(await readFile(join(root, 'backend/crlf.py'), 'utf8'), 'value = "Grüße 日本語"\r\n');
  assert.equal(
    await readFile(join(root, 'backend/excluded.py'), 'utf8'),
    'value=  "Grüße 日本語"\n',
  );
});

void test('missing Python reports a formatting failure without changing files', async () => {
  const root = await fixture();
  await writeFile(join(root, 'backend/new.py'), 'value=  2\n');
  await assert.rejects(
    formatBackend(
      root,
      join(root, 'backend/.codex-validation/manual'),
      join(root, 'missing-python'),
    ),
    /Backend Black formatting failed/,
  );
  assert.equal(await readFile(join(root, 'backend/new.py'), 'utf8'), 'value=  2\n');
});

void test('backend fingerprints track shared tooling and environment metadata while ignoring test output', async () => {
  const root = await fixture();
  const before = await backendFingerprint(root);
  await mkdir(join(root, 'backend/.codex-validation/manual'), { recursive: true });
  await writeFile(join(root, 'backend/.codex-validation/manual/log'), 'output');
  await mkdir(join(root, 'backend/tests/.pytest_cache_old'), { recursive: true });
  await writeFile(join(root, 'backend/tests/.pytest_cache_old/log'), 'output');
  assert.equal(await backendFingerprint(root), before);
  await mkdir(join(root, '.codex/validation'), { recursive: true });
  await writeFile(join(root, '.codex/validation/shared.mts'), 'export {};');
  const tooling = await backendFingerprint(root);
  assert.notEqual(tooling, before);
  const metadata =
    process.platform === 'win32'
      ? 'backend/.venv/Lib/site-packages/black.dist-info'
      : 'backend/.venv/lib/python3.13/site-packages/black.dist-info';
  await mkdir(join(root, metadata), { recursive: true });
  await writeFile(join(root, metadata, 'METADATA'), 'Version: changed');
  assert.notEqual(await backendFingerprint(root), tooling);
});

void test('directory links cannot redirect formatting outside the backend', async () => {
  const root = await fixture();
  const outside = await mkdtemp(join(tmpdir(), 'ai-service-hook-outside-'));
  await writeFile(join(outside, 'linked.py'), 'value=  2\n');
  await symlink(
    outside,
    join(root, 'backend/linked'),
    process.platform === 'win32' ? 'junction' : 'dir',
  );
  const { sourcePath } = await import('./shared.mts');
  await assert.rejects(sourcePath(root, 'backend', 'backend/linked/linked.py'), /outside backend/);
  assert.equal(await readFile(join(outside, 'linked.py'), 'utf8'), 'value=  2\n');
});
