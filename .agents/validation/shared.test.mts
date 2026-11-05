import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { changedFiles } from './shared.mts';

void test('guarded writes reject files changed after formatting was prepared', async () => {
  const { writeFormatting } = await import('./shared.mts');
  const root = await mkdtemp(join(tmpdir(), 'ai-service-hook-write-'));
  const path = join(root, 'source.py');
  await writeFile(path, 'concurrent edit');
  await assert.rejects(
    writeFormatting([{ path, name: 'source.py', original: 'before', formatted: 'after' }]),
    /File changed during formatting/,
  );
  assert.equal(await readFile(path, 'utf8'), 'concurrent edit');
});

void test('change discovery includes staged edits even when the worktree matches HEAD', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-hook-index-'));
  await mkdir(join(root, 'backend'));
  const path = join(root, 'backend/source.py');
  const original = 'value=  1\n';
  function git(args: string[]): string {
    return execFileSync('git', args, {
      cwd: root,
      encoding: 'utf8',
      windowsHide: true,
    });
  }
  git(['init', '-q']);
  git(['config', 'core.autocrlf', 'false']);
  await writeFile(path, original);
  git(['add', '.']);
  git([
    '-c',
    'user.name=Hook test',
    '-c',
    'user.email=hook@example.invalid',
    'commit',
    '-qm',
    'Fixture',
  ]);
  await writeFile(path, 'value = 2\n');
  git(['add', 'backend/source.py']);
  await writeFile(path, original);
  assert.deepEqual(changedFiles(root, 'backend/'), ['backend/source.py']);
  assert.equal(git(['show', ':backend/source.py']), 'value = 2\n');
});

void test('shared change discovery supports staged files before the first commit', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-hook-initial-'));
  await mkdir(join(root, 'backend'));
  await writeFile(join(root, 'backend/source.py'), 'value=  1\n');
  execFileSync('git', ['init', '-q'], { cwd: root, windowsHide: true });
  execFileSync('git', ['add', '.'], { cwd: root, windowsHide: true });
  assert.deepEqual(changedFiles(root, 'backend/'), ['backend/source.py']);
});

void test('shared change discovery refuses unresolved merge conflicts', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-hook-conflict-'));
  await mkdir(join(root, 'backend'));
  await writeFile(join(root, 'backend/conflict.py'), 'value = 1\n');
  execFileSync('git', ['init', '-q'], { cwd: root });
  const blob = execFileSync('git', ['hash-object', '-w', 'backend/conflict.py'], {
    cwd: root,
    encoding: 'utf8',
  }).trim();
  execFileSync('git', ['update-index', '--index-info'], {
    cwd: root,
    input: `100644 ${blob} 1\tbackend/conflict.py\n100644 ${blob} 2\tbackend/conflict.py\n100644 ${blob} 3\tbackend/conflict.py\n`,
  });
  assert.throws(() => changedFiles(root, 'backend/'), /merge conflicts/);
});
