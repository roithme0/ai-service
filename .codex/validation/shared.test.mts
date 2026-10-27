import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  changedFiles,
  validateStop as sharedValidateStop,
  type ValidationDependencies,
  type ValidationState,
  type HookOutput,
} from './shared.mts';

function validateStop(
  state: ValidationState,
  continued: boolean,
  dependencies: ValidationDependencies,
): Promise<HookOutput> {
  return sharedValidateStop(state, continued, dependencies, {
    label: 'Fixture',
    formatter: 'Formatter',
    success: 'Checks passed.',
    retry: 'fixture validation',
  });
}

function fixture(): {
  dependencies: ValidationDependencies;
  calls: string[];
  content: { value: string };
} {
  const calls: string[] = [];
  const content = { value: 'before' };
  return {
    calls,
    content,
    dependencies: {
      fingerprint: () => Promise.resolve(content.value),
      hasChanges: () => true,
      format: () => {
        calls.push('format');
        return Promise.resolve({ checked: [], formatted: [] });
      },
      lint: () => {
        calls.push('lint');
        return Promise.resolve();
      },
      test: () => {
        calls.push('test');
        return Promise.resolve();
      },
    },
  };
}

void test('discussion turns skip validation even with uncommitted frontend files', async () => {
  const { dependencies, calls } = fixture();
  assert.deepEqual(await validateStop({ promptFingerprint: 'before' }, false, dependencies), {});
  assert.deepEqual(calls, []);
});

void test('continuations skip unchanged scopes without pending validation', async () => {
  const { dependencies, calls } = fixture();
  assert.deepEqual(await validateStop({ promptFingerprint: 'before' }, true, dependencies), {});
  assert.deepEqual(calls, []);
});

void test('formats before lint and tests and invalidates successful validation on later edits', async () => {
  const { dependencies, calls, content } = fixture();
  const state: ValidationState = { promptFingerprint: 'old' };
  dependencies.format = () => {
    calls.push('format');
    content.value = 'formatted';
    return Promise.resolve({ checked: ['a.ts'], formatted: ['a.ts'] });
  };
  const first = await validateStop(state, false, dependencies);
  assert.equal(first.decision, 'block');
  assert.deepEqual(calls, ['format', 'lint', 'test']);
  assert.equal(state.successfulFingerprint, 'formatted');
  dependencies.format = () => Promise.resolve({ checked: [], formatted: [] });
  calls.length = 0;
  assert.deepEqual(await validateStop(state, true, dependencies), {});
  assert.deepEqual(calls, []);
  content.value = 'edited again';
  await validateStop(state, true, dependencies);
  assert.deepEqual(calls, ['lint', 'test']);
  assert.equal(state.successfulFingerprint, 'edited again');
});

void test('failures never become successes and continuation feedback is bounded', async () => {
  const { dependencies, calls } = fixture();
  const state: ValidationState = { promptFingerprint: 'old' };
  dependencies.lint = () => Promise.reject(new Error('existing lint debt'));
  const first = await validateStop(state, false, dependencies);
  assert.equal(first.decision, 'block');
  assert.match(first.reason ?? '', /existing lint debt/);
  assert.equal(state.successfulFingerprint, undefined);
  assert.deepEqual(calls, ['format']);
  const next = await validateStop(state, true, dependencies);
  assert.equal(next.decision, undefined);
  assert.match(next.systemMessage ?? '', /validation as incomplete/);
  assert.equal(state.successfulFingerprint, undefined);
});

void test('test failures are not cached and a successful retry runs the full validation', async () => {
  const { dependencies, calls } = fixture();
  const state: ValidationState = { promptFingerprint: 'old' };
  dependencies.test = () => Promise.reject(new Error('test failed'));
  const first = await validateStop(state, false, dependencies);
  assert.equal(first.decision, 'block');
  assert.match(first.reason ?? '', /test failed/);
  assert.equal(state.successfulFingerprint, undefined);
  const next = await validateStop(state, true, dependencies);
  assert.equal(next.decision, undefined);
  assert.match(next.systemMessage ?? '', /test failed/);
  dependencies.test = () => {
    calls.push('test');
    return Promise.resolve();
  };
  calls.length = 0;
  assert.deepEqual(await validateStop(state, true, dependencies), {});
  assert.deepEqual(calls, ['format', 'lint', 'test']);
  assert.equal(state.successfulFingerprint, 'before');
});

void test('concurrent edits invalidate an otherwise successful test run', async () => {
  const { dependencies, content } = fixture();
  const state: ValidationState = { promptFingerprint: 'old' };
  dependencies.test = () => {
    content.value = 'concurrent edit';
    return Promise.resolve();
  };
  assert.equal((await validateStop(state, false, dependencies)).decision, 'block');
  assert.equal(state.successfulFingerprint, undefined);
});

void test('environment checks rerun cached content on changed turns but skip discussion', async () => {
  const { dependencies, calls } = fixture();
  dependencies.reuseSuccess = false;
  const state: ValidationState = {
    promptFingerprint: 'old',
    successfulFingerprint: 'before',
  };
  assert.deepEqual(await validateStop(state, false, dependencies), {});
  assert.deepEqual(calls, ['format', 'lint', 'test']);
  calls.length = 0;
  state.promptFingerprint = 'before';
  assert.deepEqual(await validateStop(state, false, dependencies), {});
  assert.deepEqual(calls, []);
  state.promptFingerprint = 'old';
  dependencies.test = () => Promise.reject(new Error('Docker unavailable'));
  assert.match((await validateStop(state, false, dependencies)).reason ?? '', /Docker unavailable/);
});

void test('formatter failures prevent linting and remain visible', async () => {
  const { dependencies, calls } = fixture();
  dependencies.format = () => Promise.reject(new Error('cannot parse changed file'));
  const output = await validateStop({ promptFingerprint: 'old' }, false, dependencies);
  assert.match(output.reason ?? '', /cannot parse changed file/);
  assert.deepEqual(calls, []);
});

void test('missing snapshots validate a dirty worktree and skip a clean one', async () => {
  const { dependencies, calls } = fixture();
  dependencies.hasChanges = () => false;
  assert.deepEqual(await validateStop({}, false, dependencies), {});
  assert.deepEqual(calls, []);
  dependencies.hasChanges = () => true;
  await validateStop({}, false, dependencies);
  assert.deepEqual(calls, ['format', 'lint', 'test']);
});

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

void test('combined hook validates affected scopes independently and reports both failures with one continuation', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-hook-scopes-'));
  const driver = join(root, 'driver.mts');
  const engine = new URL('./shared.mts', import.meta.url).href;
  await writeFile(
    driver,
    `
    import { readFile, appendFile } from 'node:fs/promises';
    import { join } from 'node:path';
    import { runHook, type ValidationProfile } from ${JSON.stringify(engine)};
    const root = ${JSON.stringify(root)};
    const profiles: ValidationProfile[] = ['frontend', 'backend'].map((scope) => ({
      scope,
      policy: { label: scope, formatter: 'Formatter', success: 'Passed.', retry: scope },
      dependencies: () => ({
        fingerprint: () => readFile(join(root, scope + '.txt'), 'utf8'),
        hasChanges: () => true,
        format: async () => ({ checked: [], formatted: [] }),
        test: async () => {
          await appendFile(join(root, 'calls.txt'), scope + '\\n');
          const content = await readFile(join(root, scope + '.txt'), 'utf8');
          if (content === 'fail') throw new Error(scope + ' failed');
        },
      }),
    }));
    await runHook(root, profiles, process.argv[2] === 'start', async () => {
      await appendFile(join(root, 'shared.txt'), 'shared\\n');
    });
  `,
  );
  function invoke(mode: string, continued = false): HookOutput {
    const result = spawnSync(process.execPath, [driver, mode], {
      cwd: root,
      encoding: 'utf8',
      windowsHide: true,
      input: JSON.stringify({
        session_id: 'fixture',
        stop_hook_active: continued,
      }),
    });
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout) as HookOutput;
  }
  for (const scope of ['frontend', 'backend'])
    await writeFile(join(root, `${scope}.txt`), 'before');
  assert.deepEqual(invoke('start'), {});
  assert.deepEqual(invoke('stop'), {});
  await assert.rejects(readFile(join(root, 'shared.txt'), 'utf8'), {
    code: 'ENOENT',
  });
  await writeFile(join(root, 'backend.txt'), 'edited');
  assert.deepEqual(invoke('stop'), {});
  assert.equal(await readFile(join(root, 'calls.txt'), 'utf8'), 'backend\n');
  assert.deepEqual(invoke('stop'), {});
  assert.equal(await readFile(join(root, 'calls.txt'), 'utf8'), 'backend\n');
  for (const scope of ['frontend', 'backend']) await writeFile(join(root, `${scope}.txt`), 'fail');
  const failure = invoke('stop');
  assert.equal(failure.decision, 'block');
  assert.match(failure.reason ?? '', /frontend failed/);
  assert.match(failure.reason ?? '', /backend failed/);
  const retry = invoke('stop', true);
  assert.equal(await readFile(join(root, 'shared.txt'), 'utf8'), 'shared\nshared\nshared\n');
  assert.equal(retry.decision, undefined);
  assert.match(retry.systemMessage ?? '', /frontend failed/);
  assert.match(retry.systemMessage ?? '', /backend failed/);
});
