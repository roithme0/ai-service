import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, rename, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';
import { fingerprint, formatFrontend, frontendProfile, frontendRequire } from './frontend.mts';
import { e2eProfile, testE2E, waitForGateway } from './e2e.mts';
import type { runCheck } from './shared.mts';
import { backendProfile } from './backend.mts';

const { ESLint } = frontendRequire('eslint') as typeof import('eslint');
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '../../frontend');

function textLinter(cwd: string): InstanceType<typeof ESLint> {
  return new ESLint({
    cwd,
    overrideConfig: {
      languageOptions: {
        // CI single-run programs read disk; these tests lint replacement source text.
        parserOptions: { disallowAutomaticSingleRunInference: true },
      },
    },
  });
}

void test('missing Playwright fails before any Docker command', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-e2e-prerequisites-'));
  const run: typeof runCheck = () => {
    assert.fail('Docker must not run without Playwright installed');
  };
  await assert.rejects(
    testE2E(root, join(root, 'cache'), run),
    /Incomplete E2E validation: missing installed Playwright dependency/,
  );
});

void test('E2E collects diagnostics for preparation failures and preserves the original error', async () => {
  for (const failure of ['Docker availability', 'Docker build and startup', 'Gateway restart']) {
    for (const diagnosticsFail of [false, true]) {
      const root = await mkdtemp(join(tmpdir(), 'ai-service-e2e-diagnostics-'));
      const cli = join(root, 'frontend/node_modules/@playwright/test/cli.js');
      await mkdir(dirname(cli), { recursive: true });
      await writeFile(cli, '');
      const cache = join(root, 'cache');
      const original = new Error(failure);
      const calls: Parameters<typeof runCheck>[] = [];
      const run: typeof runCheck = async (...args) => {
        calls.push(args);
        if (args[1] === failure) throw original;
        if (args[1] === 'E2E failure diagnostics') {
          if (diagnosticsFail) throw new Error('diagnostic command failed');
          await writeFile(args[3], 'diagnostic output');
        }
        return '';
      };
      await assert.rejects(testE2E(root, cache, run), (error: unknown) => error === original);
      assert.equal(calls[0][1], 'Docker availability');
      assert.deepEqual(calls[0][2], ['info', '--format', '{{.ServerVersion}}']);
      const diagnostics = calls.filter((args) => args[1] === 'E2E failure diagnostics');
      assert.deepEqual(diagnostics.map((args) => args[2]), [
        ['compose', '-f', 'deployment/docker-compose-local.yml', 'ps', '--all'],
        ['compose', '-f', 'deployment/docker-compose-local.yml', 'logs', '--no-color', '--tail', '2000'],
      ]);
      for (const args of diagnostics) {
        assert.equal(args[5], 'docker');
        assert.equal(args[7]?.GATEWAY_PORT, calls[0][7]?.GATEWAY_PORT);
      }
      for (const name of ['services', 'services-logs']) {
        const report = await readFile(join(cache, `${name}${diagnosticsFail ? '-error' : ''}.log`), 'utf8');
        assert.match(report, diagnosticsFail ? /diagnostic command failed/ : /diagnostic output/);
      }
    }
  }
});

void test('shared validation and Codex adapter changes invalidate every validation scope', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-validation-scopes-'));
  execFileSync('git', ['init', '-q'], { cwd: root });
  const profiles = [
    frontendProfile(root).dependencies(root),
    backendProfile(root).dependencies(root),
    e2eProfile(root).dependencies(root),
  ];
  let previous = await Promise.all(profiles.map((profile) => profile.fingerprint()));
  for (const name of ['.agents/validation/shared.mts', '.codex/validate.mts']) {
    await mkdir(dirname(join(root, name)), { recursive: true });
    await writeFile(join(root, name), 'changed');
    const current = await Promise.all(profiles.map((profile) => profile.fingerprint()));
    for (let index = 0; index < profiles.length; index++) {
      assert.notEqual(current[index], previous[index]);
      assert.equal(profiles[index].hasChanges(), true);
    }
    previous = current;
  }
});

void test('end-to-end scope includes backend and gateway edits without expanding frontend unit scope', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-e2e-'));
  execFileSync('git', ['init', '-q'], { cwd: root });
  const dependencies = e2eProfile(root).dependencies(root);
  const unitFingerprint = await fingerprint(root);
  let previous = await dependencies.fingerprint();
  assert.equal(dependencies.hasChanges(), false);
  for (const name of [
    'backend/app/main.py',
    'deployment/gateway/nginx.conf',
    'frontend/e2e/test.spec.ts',
  ]) {
    await mkdir(dirname(join(root, name)), { recursive: true });
    await writeFile(join(root, name), 'changed');
    assert.equal(dependencies.hasChanges(), true);
    const current = await dependencies.fingerprint();
    assert.notEqual(current, previous);
    previous = current;
    if (!name.startsWith('frontend/')) assert.equal(await fingerprint(root), unitFingerprint);
  }
  await mkdir(join(root, 'docs'));
  await writeFile(join(root, 'docs/notes.md'), 'documentation');
  assert.equal(await dependencies.fingerprint(), previous);
  assert.equal(dependencies.reuseSuccess, false);
});

void test('gateway readiness retries startup errors and requires both frontend and backend', async () => {
  const paths: string[] = [];
  let backendRequests = 0;
  let unavailable = false;
  const server = createServer((request, response) => {
    paths.push(request.url ?? '');
    if (request.url === '/api/openapi.json') backendRequests++;
    response.statusCode = unavailable
      ? 503
      : request.url === '/api/openapi.json' && backendRequests < 2
        ? 502
        : 200;
    response.end();
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const address = server.address();
    assert.ok(address && typeof address !== 'string');
    const baseURL = `http://127.0.0.1:${address.port}`;
    await waitForGateway(baseURL, 5_000);
    assert.deepEqual(paths, ['/', '/api/openapi.json', '/', '/api/openapi.json']);
    unavailable = true;
    await assert.rejects(waitForGateway(baseURL, 0), /did not become ready.*HTTP 503/);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
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
  await mkdir(join(root, '.agents/.codex-validation'), { recursive: true });
  await writeFile(
    join(root, '.agents/.gitignore'),
    await readFile(new URL('../../.agents/.gitignore', import.meta.url)),
  );
  for (const scope of ['frontend', 'backend', 'e2e']) {
    const path = `.agents/.codex-validation/${scope}/state.json`;
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), '{}');
    assert.equal(git(root, ['check-ignore', path]).trim(), path);
  }
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

void test('configuration checks typed code, external and inline templates, and scripts', async () => {
  const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '../../frontend');
  const eslint = textLinter(frontend);
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

void test('validation TypeScript receives strict lint rules from its own configuration', async () => {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const eslint = textLinter(join(root, '.agents/validation'));
  const [result] = await eslint.lintText('Promise.resolve(1);', {
    filePath: join(root, '.agents/validation/shared.mts'),
  });
  assert.ok(
    result.messages.some((message) => message.ruleId === '@typescript-eslint/no-floating-promises'),
  );
});

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
  const result = await formatFrontend(root);
  assert.deepEqual(result.formatted, [
    'frontend/new file ä.ts',
    'frontend/staged.ts',
    'frontend/unstaged.ts',
  ]);
  assert.equal(await readFile(join(root, 'frontend/unchanged.ts'), 'utf8'), original);
  assert.equal(git(root, ['show', ':frontend/staged.ts']), stagedBefore);
  assert.deepEqual((await formatFrontend(root)).formatted, []);
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
  assert.deepEqual(await formatFrontend(root), {
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
  const result = await formatFrontend(root);
  assert.deepEqual(result.formatted, ['frontend/template.html']);
  assert.match(await readFile(join(root, 'frontend/template.html'), 'utf8'), /@if \(visible\)/);
  assert.deepEqual((await formatFrontend(root)).formatted, []);
});

void test('parse errors prevent any planned formatting writes', async () => {
  const root = await fixture();
  commit(root);
  const original = 'export const value=  1';
  await writeFile(join(root, 'frontend/a.ts'), original);
  await writeFile(join(root, 'frontend/z.ts'), 'export const =');
  await assert.rejects(formatFrontend(root));
  assert.equal(await readFile(join(root, 'frontend/a.ts'), 'utf8'), original);
});
