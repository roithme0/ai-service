import { access, mkdir, mkdtemp, writeFile } from 'node:fs/promises';
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
  '.agents/validation/',
];

const compose = ['compose', '-f', 'deployment/docker-compose-local.yml'];

interface E2EContext {
  root: string;
  cache: string;
  env: NodeJS.ProcessEnv;
  run: typeof runCheck;
}

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

export async function testE2E(
  root: string,
  cache: string,
  run: typeof runCheck = runCheck,
): Promise<void> {
  await mkdir(cache, { recursive: true });
  const env = {
    ...process.env,
    GATEWAY_PORT: process.env['GATEWAY_PORT'] || '8004',
  };
  const frontend = join(root, 'frontend');
  const cli = join(frontend, 'node_modules/@playwright/test/cli.js');
  await access(cli).catch(() => {
    throw new Error(
      'Incomplete E2E validation: missing installed Playwright dependency (run npm ci in frontend).',
    );
  });
  const context: E2EContext = { root, cache, env, run };
  try {
    await prepareDocker(context);
    const baseURL = `http://localhost:${env.GATEWAY_PORT}`;
    await waitForGateway(baseURL);
    await runPlaywright(context, cli, baseURL);
  } catch (error: unknown) {
    await collectDiagnostics(context);
    throw error;
  }
}

async function prepareDocker({ root, cache, env, run }: E2EContext): Promise<void> {
  await run(
    root,
    'Docker availability',
    ['info', '--format', '{{.ServerVersion}}'],
    join(cache, 'docker-info.log'),
    30_000,
    'docker',
    undefined,
    env,
  );
  await run(
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
  await run(
    root,
    'Gateway restart',
    [...compose, 'restart', 'gateway'],
    join(cache, 'gateway.log'),
    60_000,
    'docker',
    undefined,
    env,
  );
}

async function runPlaywright(
  { root, cache, env, run }: E2EContext,
  cli: string,
  baseURL: string,
): Promise<void> {
  const artifacts = await mkdtemp(join(cache, 'playwright-'));
  await run(
    join(root, 'frontend'),
    'Playwright',
    [cli, 'test', '--output', join(artifacts, 'test-results')],
    join(cache, 'playwright.log'),
    180_000,
    process.execPath,
    undefined,
    {
      ...env,
      PLAYWRIGHT_BASE_URL: baseURL,
      PLAYWRIGHT_HTML_OUTPUT_DIR: join(artifacts, 'html-report'),
      PLAYWRIGHT_HTML_OPEN: 'never',
    },
  );
}

async function collectDiagnostics({ root, cache, env, run }: E2EContext): Promise<void> {
  for (const [command, name] of [
    ['ps', 'services'],
    ['logs', 'services-logs'],
  ]) {
    try {
      await run(
        root,
        'E2E failure diagnostics',
        [
          ...compose,
          command,
          ...(command === 'logs' ? ['--no-color', '--tail', '2000'] : ['--all']),
        ],
        join(cache, `${name}.log`),
        30_000,
        'docker',
        undefined,
        env,
      );
    } catch (diagnosticError: unknown) {
      await writeFile(join(cache, `${name}-error.log`), String(diagnosticError)).catch(() => {});
    }
  }
}

export function e2eProfile(root: string): ValidationProfile {
  return {
    scope: 'e2e',
    policy: {
      label: 'End-to-end',
      formatter: 'Formatter',
      success: 'Docker preparation and Playwright passed.',
      retry: 'end-to-end validation: node .agents/validation/e2e.mts from the repository root',
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
  if (process.argv.length !== 2) throw new Error('Usage: node .agents/validation/e2e.mts');
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  await testE2E(root, join(root, '.agents/.codex-validation/e2e/manual'));
  process.stdout.write('Docker preparation and Playwright passed.\n');
}
