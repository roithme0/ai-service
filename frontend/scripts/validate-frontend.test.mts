import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, rename, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { ESLint } from 'eslint';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  validateStop,
  fingerprint,
  type ValidationDependencies,
  type ValidationState,
} from './validate-frontend.mts';

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

void test('formatter failures prevent linting and remain visible', async () => {
  const { dependencies, calls } = fixture();
  dependencies.format = () => Promise.reject(new Error('cannot parse changed file'));
  const output = await validateStop({ promptFingerprint: 'old' }, false, dependencies);
  assert.match(output.reason ?? '', /cannot parse changed file/);
  assert.deepEqual(calls, []);
});

void test('fingerprints include new, changed, renamed, and deleted inputs but exclude caches', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-lint-'));
  const frontend = join(root, 'frontend');
  await mkdir(join(frontend, '.angular/cache'), { recursive: true });
  await mkdir(join(frontend, '.codex-validation'), { recursive: true });
  await writeFile(join(frontend, '.gitignore'), '.angular/cache/\n.codex-validation/\n');
  await writeFile(join(frontend, 'source.ts'), 'export const value = 1;');
  execFileSync('git', ['init', '-q'], { cwd: root });
  execFileSync('git', ['add', 'frontend/source.ts'], { cwd: root });
  const initial = await fingerprint(root);
  await writeFile(join(frontend, '.angular/cache/state.json'), '{}');
  await writeFile(join(frontend, '.codex-validation/state.json'), '{}');
  assert.equal(await fingerprint(root), initial);
  await writeFile(join(frontend, 'source.ts'), 'export const value = 2;');
  const edited = await fingerprint(root);
  assert.notEqual(edited, initial);
  await writeFile(join(frontend, 'new.ts'), 'export const added = true;');
  const added = await fingerprint(root);
  assert.notEqual(added, edited);
  await rename(join(frontend, 'source.ts'), join(frontend, 'renamed.ts'));
  assert.notEqual(await fingerprint(root), added);
});

void test(
  'PowerShell wrapper dispatches start and stop without linting an unchanged turn',
  {
    skip: process.platform !== 'win32',
  },
  () => {
    const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
    const session = `lint-wrapper-test-${process.pid}`;
    for (const mode of ['start', 'stop']) {
      const result = spawnSync(
        'powershell.exe',
        [
          '-NoProfile',
          '-NonInteractive',
          '-ExecutionPolicy',
          'Bypass',
          '-File',
          join(root, '.codex/validate-frontend.ps1'),
          '-Mode',
          mode,
        ],
        {
          cwd: root,
          encoding: 'utf8',
          windowsHide: true,
          input: JSON.stringify({
            session_id: session,
            stop_hook_active: false,
          }),
        },
      );
      assert.equal(result.status, 0, result.stderr);
      assert.equal(result.stdout, '{}');
    }
  },
);

void test('configuration checks typed code, external and inline templates, and scripts', async () => {
  const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const eslint = new ESLint({ cwd: frontend });
  const [typescript] = await eslint.lintText('Promise.resolve(1);', {
    filePath: join(frontend, 'src/main.ts'),
  });
  assert.ok(
    typescript.messages.some(
      (message) => message.ruleId === '@typescript-eslint/no-floating-promises',
    ),
  );
  const [library] = await eslint.lintText('Promise.resolve(1);', {
    filePath: join(frontend, 'projects/chat-ui/conversation/src/session-controller.ts'),
  });
  assert.ok(
    library.messages.some(
      (message) => message.ruleId === '@typescript-eslint/no-floating-promises',
    ),
  );
  const [template] = await eslint.lintText('<img src="photo.png">', {
    filePath: join(frontend, 'src/app/app.component.html'),
  });
  assert.ok(
    template.messages.some((message) => message.ruleId === '@angular-eslint/template/alt-text'),
  );
  const [inline] = await eslint.lintText(
    "import { Component } from '@angular/core'; @Component({selector: 'app-test', template: '<img src=\"photo.png\">'}) export class TestComponent {}",
    { filePath: join(frontend, 'src/app/app.component.ts') },
  );
  assert.ok(
    inline.messages.some((message) => message.ruleId === '@angular-eslint/template/alt-text'),
  );
  const [script] = await eslint.lintText('missingFunction();', {
    filePath: join(frontend, 'scripts/conversation-contract.mjs'),
  });
  assert.ok(script.messages.some((message) => message.ruleId === 'no-undef'));
  assert.equal(
    await eslint.isPathIgnored(
      join(frontend, 'projects/chat-ui/conversation/generated/types.gen.ts'),
    ),
    true,
  );
});
