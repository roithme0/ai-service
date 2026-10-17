import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { formatChangedFiles } from './format-changed.mts';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');

async function fixture(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-format-'));
  await mkdir(join(root, 'frontend/projects/chat-ui/conversation/generated'), {
    recursive: true,
  });
  await mkdir(join(root, 'backend'));
  for (const config of ['.prettierrc', '.prettierignore', '.gitignore']) {
    await writeFile(join(root, 'frontend', config), await readFile(join(frontend, config)));
  }
  execFileSync('git', ['init', '-q'], { cwd: root });
  execFileSync('git', ['config', 'user.name', 'Formatter test'], { cwd: root });
  execFileSync('git', ['config', 'user.email', 'formatter@example.invalid'], {
    cwd: root,
  });
  execFileSync('git', ['config', 'core.autocrlf', 'false'], { cwd: root });
  return root;
}

function git(root: string, args: string[]): string {
  return execFileSync('git', args, { cwd: root, encoding: 'utf8' });
}

function commit(root: string): void {
  git(root, ['add', '.']);
  git(root, ['commit', '-qm', 'Fixture']);
}

void test('formats staged, unstaged and new files, preserving unchanged files and index', async () => {
  const root = await fixture();
  const original = 'export const value=  1';
  for (const name of ['unchanged.ts', 'staged.ts', 'unstaged.ts']) {
    await writeFile(join(root, 'frontend', name), original);
  }
  commit(root);
  await writeFile(join(root, 'frontend/staged.ts'), 'export const value=  2');
  git(root, ['add', 'frontend/staged.ts']);
  const stagedBefore = git(root, ['show', ':frontend/staged.ts']);
  await writeFile(join(root, 'frontend/unstaged.ts'), 'export const value=  3');
  await writeFile(join(root, 'frontend/new file ä.ts'), 'export const value=  4');
  const result = await formatChangedFiles(root);
  assert.deepEqual(result.formatted, [
    'frontend/new file ä.ts',
    'frontend/staged.ts',
    'frontend/unstaged.ts',
  ]);
  assert.equal(await readFile(join(root, 'frontend/unchanged.ts'), 'utf8'), original);
  assert.equal(git(root, ['show', ':frontend/staged.ts']), stagedBefore);
  assert.deepEqual((await formatChangedFiles(root)).formatted, []);
});

void test('skips generated, ignored, unsupported and backend files; handles missing tracked files', async () => {
  const root = await fixture();
  await writeFile(join(root, 'frontend/tracked.ts'), 'export const value=1');
  commit(root);
  git(root, ['mv', 'frontend/tracked.ts', 'backend/moved.ts']);
  const ignored = [
    'frontend/projects/chat-ui/conversation/generated/types.gen.ts',
    'frontend/package-lock.json',
    'frontend/node_modules/local.ts',
    'frontend/dist/output.ts',
    'frontend/image.png',
    'backend/new.ts',
  ];
  for (const name of ignored) {
    await mkdir(dirname(join(root, name)), { recursive: true });
    await writeFile(join(root, name), 'not valid source');
  }
  assert.deepEqual(await formatChangedFiles(root), {
    checked: [],
    formatted: [],
  });
  for (const name of ignored) {
    assert.equal(await readFile(join(root, name), 'utf8'), 'not valid source');
  }
});

void test('formats Angular control flow using the Angular parser', async () => {
  const root = await fixture();
  commit(root);
  await writeFile(join(root, 'frontend/template.html'), '@if(visible){<span>{{value}}</span>}');
  const result = await formatChangedFiles(root);
  assert.deepEqual(result.formatted, ['frontend/template.html']);
  assert.match(await readFile(join(root, 'frontend/template.html'), 'utf8'), /@if \(visible\)/);
  assert.deepEqual((await formatChangedFiles(root)).formatted, []);
});

void test('parse errors prevent any planned formatting writes', async () => {
  const root = await fixture();
  commit(root);
  const original = 'export const value=  1';
  await writeFile(join(root, 'frontend/a.ts'), original);
  await writeFile(join(root, 'frontend/z.ts'), 'export const =');
  await assert.rejects(formatChangedFiles(root));
  assert.equal(await readFile(join(root, 'frontend/a.ts'), 'utf8'), original);
});
