import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  parseValidationArguments,
  describeChecks,
  validationProfiles,
  validate,
  runValidationCommand,
} from './run.mts';
import { defaultChecks, type runCheck, type ValidationFeedback } from './shared.mts';
import { backendProfile } from './backend.mts';
import { frontendProfile } from './frontend.mts';

void test('validation options default to app and tooling tests and opt in to E2E', () => {
  assert.deepEqual(parseValidationArguments([]), { scope: 'all', checks: defaultChecks });
  assert.deepEqual(
    parseValidationArguments([
      '--scope',
      'backend',
      '--app-tests=false',
      '--tooling-tests=false',
      '--shared-tooling-tests=false',
      '--e2e',
    ]),
    {
      scope: 'backend',
      checks: {
        appTests: false,
        toolingTests: false,
        sharedToolingTests: false,
        e2e: true,
      },
    },
  );
  assert.equal(parseValidationArguments(['--scope=frontend', '--e2e=false']).scope, 'frontend');
  assert.match(
    describeChecks(parseValidationArguments([])),
    /selected format, lint, app-tests, tooling-tests, shared-tooling-tests; skipped e2e/,
  );
  assert.match(
    describeChecks(parseValidationArguments(['--scope=backend'])),
    /selected format, app-tests, tooling-tests, shared-tooling-tests;/,
  );
  assert.doesNotMatch(describeChecks(parseValidationArguments(['--scope=backend'])), /lint/);
  for (const args of [
    ['--format=false'],
    ['--lint=false'],
    ['--e2e=yes'],
    ['--e2e=true=false'],
    ['--scope'],
    ['--scope', 'unknown'],
    ['--e2e', '--e2e=false'],
  ]) {
    assert.throws(() => parseValidationArguments(args));
  }
});

void test('manual validation reports formatting separately from failures', async (t) => {
  const cases: { name: string; feedback: ValidationFeedback; exitCode: number }[] = [
    { name: 'passed', feedback: {}, exitCode: 0 },
    {
      name: 'formatted',
      feedback: { message: 'Formatted source.ts. Review the diff.' },
      exitCode: 0,
    },
    { name: 'failed', feedback: { message: 'Lint failed.', failed: true }, exitCode: 1 },
  ];
  for (const { name, feedback, exitCode } of cases) {
    await t.test(name, async (context) => {
      const stdout: string[] = [];
      const stderr: string[] = [];
      context.mock.method(process.stdout, 'write', (chunk: string | Uint8Array): boolean => {
        stdout.push(String(chunk));
        return true;
      });
      context.mock.method(process.stderr, 'write', (chunk: string | Uint8Array): boolean => {
        stderr.push(String(chunk));
        return true;
      });
      const run: typeof validate = (root, request, options) => {
        assert.equal(root, 'fixture');
        assert.equal(request.force, true);
        assert.equal(request.start, false);
        assert.deepEqual(options, {
          scope: 'backend',
          checks: { ...defaultChecks, appTests: false },
        });
        return Promise.resolve(feedback);
      };
      assert.equal(
        await runValidationCommand('fixture', ['--scope=backend', '--app-tests=false'], run),
        exitCode,
      );
      assert.equal(stdout.join('').includes('Selected validation checks passed.'), exitCode === 0);
      assert.equal(stderr.join(''), feedback.message ? `${feedback.message}\n` : '');
    });
  }
});

void test('manual validation rejects invalid arguments and reports orchestration errors', async (t) => {
  const stderr: string[] = [];
  t.mock.method(process.stdout, 'write', (): boolean => true);
  t.mock.method(process.stderr, 'write', (chunk: string | Uint8Array): boolean => {
    stderr.push(String(chunk));
    return true;
  });
  assert.equal(
    await runValidationCommand('fixture', ['--unknown'], () => {
      assert.fail('Invalid arguments must not run validation');
    }),
    1,
  );
  assert.match(stderr.join(''), /Unknown validation option/);
  stderr.length = 0;
  assert.equal(
    await runValidationCommand('fixture', [], () => Promise.reject(new Error('Unavailable'))),
    1,
  );
  assert.equal(stderr.join(''), 'Unavailable\n');
});

void test('profile selection excludes Docker by default and independently skips scope tests', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-check-selection-'));
  assert.deepEqual(
    (await validationProfiles(root)).map(({ scope }) => scope),
    ['frontend', 'backend'],
  );
  const checks = { ...defaultChecks, appTests: false, toolingTests: false, e2e: true };
  const profiles = await validationProfiles(root, { scope: 'backend', checks });
  assert.deepEqual(
    profiles.map(({ scope }) => scope),
    ['backend', 'e2e'],
  );
  for (const profile of await validationProfiles(root, { checks: { ...checks, e2e: false } })) {
    await profile.dependencies(root).test();
  }
});

void test('app and scope tooling tests execute exactly the selected commands', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-independent-checks-'));
  for (const createProfile of [frontendProfile, backendProfile]) {
    for (const appTests of [false, true]) {
      for (const toolingTests of [false, true]) {
        const calls: string[] = [];
        const run: typeof runCheck = (_cwd, label) => {
          calls.push(label);
          return Promise.resolve('');
        };
        const profile = createProfile(root, { ...defaultChecks, appTests, toolingTests }, run);
        await profile.dependencies(root).test();
        const expected: string[] = [];
        if (toolingTests) expected.push(`${profile.policy.label} tooling tests`);
        if (appTests)
          expected.push(
            ...(profile.scope === 'frontend'
              ? ['Frontend tests (ai-service-frontend)', 'Frontend tests (chat-ui)']
              : ['Backend pytest']),
          );
        assert.deepEqual(calls, expected);
      }
    }
  }
});

void test('orchestration runs shared-only checks and honors their disabled flag', async () => {
  const root = await mkdtemp(join(tmpdir(), 'ai-service-shared-selection-'));
  await mkdir(join(root, 'backend'));
  execFileSync('git', ['init', '-q'], { cwd: root, windowsHide: true });
  const request = { sessionId: 'fixture', start: false, continued: false, force: true };
  const checks = { ...defaultChecks, appTests: false, toolingTests: false };
  assert.deepEqual(
    await validate(root, request, {
      scope: 'backend',
      checks: { ...checks, sharedToolingTests: false },
    }),
    {},
  );
  const result = await validate(root, request, { scope: 'backend', checks });
  assert.match(result.message ?? '', /Shared validation tests failed/);
});
