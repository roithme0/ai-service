import { mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { setTimeout } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { fingerprint, git, runCheck, type ValidationProfile } from './shared.mts';

const inputs = [
  'frontend/',
  'backend/',
  'deployment/docker-compose-local.yml',
  'deployment/gateway/',
  '.editorconfig',
  '.codex/',
];

export async function waitForGateway(baseURL: string, timeout = 60_000): Promise<void> {
  const deadline = Date.now() + timeout;
  let failure: string;
  do {
    try {
      for (const path of ['/', '/api/openapi.json']) {
        const response = await fetch(new URL(path, baseURL), {
          signal: AbortSignal.timeout(3_000),
        });
        await response.body?.cancel();
        if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
      }
      return;
    } catch (error: unknown) {
      failure = error instanceof Error ? error.message : String(error);
    }
    await setTimeout(500);
  } while (Date.now() < deadline);
  throw new Error(`Docker gateway at ${baseURL} did not become ready: ${failure}`);
}

export async function testE2E(root: string, cache: string): Promise<void> {
  await mkdir(cache, { recursive: true });
  const env = { ...process.env, GATEWAY_PORT: process.env['GATEWAY_PORT'] || '8004' };
  const compose = ['compose', '-f', 'deployment/docker-compose-local.yml'];
  await runCheck(
    root,
    'Docker build and startup',
    [...compose, 'up', '-d', '--build', '--wait', '--wait-timeout', '60'],
    join(cache, 'docker.log'),
    600_000,
    'docker',
    undefined,
    env,
  );
  // Nginx must resolve upstream addresses again after container replacement.
  await runCheck(
    root,
    'Gateway restart',
    [...compose, 'restart', 'gateway'],
    join(cache, 'gateway.log'),
    60_000,
    'docker',
    undefined,
    env,
  );
  const baseURL = `http://localhost:${env.GATEWAY_PORT}`;
  await waitForGateway(baseURL);
  const frontend = join(root, 'frontend');
  await runCheck(
    frontend,
    'Playwright',
    [join(frontend, 'node_modules/@playwright/test/cli.js'), 'test'],
    join(cache, 'playwright.log'),
    180_000,
    process.execPath,
    undefined,
    { ...env, PLAYWRIGHT_BASE_URL: baseURL },
  );
}

export function e2eProfile(root: string): ValidationProfile {
  return {
    scope: 'e2e',
    policy: {
      label: 'End-to-end',
      formatter: 'Formatter',
      success: 'Docker preparation and Playwright passed.',
      retry: 'end-to-end validation: node .codex/validation/e2e.mts from the repository root',
    },
    dependencies: (cache) => ({
      reuseSuccess: false,
      fingerprint: () => fingerprint(root, inputs, ['frontend/node_modules/.package-lock.json']),
      hasChanges: () => git(root, ['status', '--porcelain', '-z', '--', ...inputs]).length > 0,
      format: () => Promise.resolve({ checked: [], formatted: [] }),
      test: () => testE2E(root, cache),
    }),
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 2) throw new Error('Usage: node .codex/validation/e2e.mts');
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  await testE2E(root, join(root, '.agents/.codex-validation/e2e/manual'));
  process.stdout.write('Docker preparation and Playwright passed.\n');
}
