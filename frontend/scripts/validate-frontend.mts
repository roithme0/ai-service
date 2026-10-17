import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { formatChangedFiles, type FormatResult } from './format-changed.mts';

export interface ValidationState {
  promptFingerprint?: string;
  successfulFingerprint?: string;
}

interface HookInput {
  session_id: string;
  stop_hook_active: boolean;
}

export interface ValidationDependencies {
  fingerprint: () => Promise<string>;
  hasChanges: () => boolean;
  format: () => Promise<FormatResult>;
  lint: () => Promise<void>;
  test: () => Promise<void>;
}

export interface HookOutput {
  decision?: 'block';
  reason?: string;
  systemMessage?: string;
}

function git(root: string, args: string[]): string[] {
  return execFileSync('git', args, { cwd: root, encoding: 'utf8' }).split('\0').filter(Boolean);
}

export async function fingerprint(root: string): Promise<string> {
  const paths = git(root, [
    'ls-files',
    '--cached',
    '--others',
    '--exclude-standard',
    '-z',
    '--',
    'frontend/',
    '.editorconfig',
    '.codex/hooks.json',
    '.codex/validate-frontend.ps1',
  ]);
  paths.push('frontend/node_modules/.package-lock.json');
  const hash = createHash('sha256').update(process.version);
  for (const name of [...new Set(paths)].sort()) {
    hash.update(name).update('\0');
    try {
      const content = await readFile(join(root, name));
      hash.update(String(content.length)).update('\0').update(content);
    } catch (error: unknown) {
      if (!(error instanceof Error && 'code' in error && error.code === 'ENOENT')) {
        throw error;
      }
      hash.update('missing');
    }
    hash.update('\0');
  }
  return hash.digest('hex');
}

function hasFrontendChanges(root: string): boolean {
  return git(root, ['status', '--porcelain', '-z', '--', 'frontend/']).length > 0;
}

async function lintFrontend(root: string, logPath: string): Promise<void> {
  const frontend = join(root, 'frontend');
  await runCheck(
    frontend,
    'Frontend lint',
    [join(frontend, 'node_modules/eslint/bin/eslint.js'), '.', '--max-warnings=0'],
    logPath,
    120_000,
  );
}

async function testFrontend(root: string, cache: string): Promise<void> {
  const frontend = join(root, 'frontend');
  await runCheck(
    frontend,
    'Frontend tooling tests',
    ['--test', 'scripts/format-changed.test.mts', 'scripts/validate-frontend.test.mts'],
    join(cache, 'tooling-tests.log'),
    120_000,
  );
  for (const project of ['ai-service-frontend', 'chat-ui']) {
    await runCheck(
      frontend,
      `Frontend tests (${project})`,
      [join(frontend, 'node_modules/@angular/cli/bin/ng.js'), 'test', project, '--watch=false'],
      join(cache, `tests-${project}.log`),
      300_000,
    );
  }
}

async function runCheck(
  frontend: string,
  label: string,
  args: string[],
  logPath: string,
  timeout: number,
): Promise<void> {
  const result = spawnSync(process.execPath, args, {
    cwd: frontend,
    encoding: 'utf8',
    timeout,
    maxBuffer: 8 * 1024 * 1024,
    windowsHide: true,
  });
  const output = [result.stdout, result.stderr, result.error?.message].filter(Boolean).join('\n');
  await writeFile(logPath, output);
  if (result.status !== 0) {
    throw new Error(`${label} failed. Full report: ${logPath}\n${output.slice(-16_000)}`);
  }
}

export async function validateStop(
  state: ValidationState,
  continued: boolean,
  dependencies: ValidationDependencies,
): Promise<HookOutput> {
  let formattedFiles: string[] = [];
  try {
    const before = await dependencies.fingerprint();
    const discussionOnly = state.promptFingerprint === before && !continued;
    if (discussionOnly || (!state.promptFingerprint && !dependencies.hasChanges())) {
      return {};
    }

    const formatting = await dependencies.format();
    formattedFiles = formatting.formatted;
    const current = await dependencies.fingerprint();
    if (current !== state.successfulFingerprint) {
      await dependencies.lint();
      await dependencies.test();
      if ((await dependencies.fingerprint()) !== current) {
        throw new Error(
          'Frontend files changed during validation. Run validation again after edits finish.',
        );
      }
      state.successfulFingerprint = current;
    }
    if (formatting.formatted.length === 0) return {};
    return feedback(
      `Prettier formatted: ${formatting.formatted.join(', ')}. Review the diff before completing. Do not undo formatting. Frontend lint and the full frontend test suite passed.`,
      continued,
    );
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    const formattingNotice =
      formattedFiles.length > 0
        ? `Prettier formatted: ${formattedFiles.join(', ')}. Review the diff; do not undo formatting.\n`
        : '';
    return feedback(
      `${formattingNotice}${message}\nFix findings in your changes and rerun frontend validation: npm run lint, node --test scripts/format-changed.test.mts scripts/validate-frontend.test.mts, and npm run test:app and npm run test:chat-ui from frontend. Do not perform a broad existing-debt cleanup without authorization. If blocked by existing debt or dependencies, report validation as incomplete and explain why; do not claim it passed.`,
      continued,
    );
  }
}

function feedback(reason: string, continued: boolean): HookOutput {
  return continued ? { systemMessage: reason } : { decision: 'block', reason };
}

function readInput(start: boolean): HookInput {
  const input: unknown = JSON.parse(readFileSync(0, 'utf8'));
  if (
    typeof input !== 'object' ||
    input === null ||
    !('session_id' in input) ||
    typeof input.session_id !== 'string' ||
    (!start && (!('stop_hook_active' in input) || typeof input.stop_hook_active !== 'boolean'))
  ) {
    throw new Error('Expected Codex session_id and, for Stop, boolean stop_hook_active.');
  }
  return {
    session_id: input.session_id,
    stop_hook_active: 'stop_hook_active' in input && input.stop_hook_active === true,
  };
}

async function readState(path: string): Promise<ValidationState> {
  try {
    const state: unknown = JSON.parse(await readFile(path, 'utf8'));
    if (typeof state !== 'object' || state === null) return {};
    return {
      promptFingerprint:
        'promptFingerprint' in state && typeof state.promptFingerprint === 'string'
          ? state.promptFingerprint
          : undefined,
      successfulFingerprint:
        'successfulFingerprint' in state && typeof state.successfulFingerprint === 'string'
          ? state.successfulFingerprint
          : undefined,
    };
  } catch (error: unknown) {
    if (
      error instanceof SyntaxError ||
      (error instanceof Error && 'code' in error && error.code === 'ENOENT')
    )
      return {};
    throw error;
  }
}

async function main(): Promise<void> {
  const start = process.argv[2] === '--start';
  let continued = false;
  try {
    if (process.argv.length !== 3 || (!start && process.argv[2] !== '--stop')) {
      throw new Error('Usage: node scripts/validate-frontend.mts --start|--stop');
    }
    const input = readInput(start);
    continued = input.stop_hook_active;
    const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
    const session = createHash('sha256').update(input.session_id).digest('hex');
    const cache = join(root, 'frontend/.codex-validation', session);
    await mkdir(cache, { recursive: true });
    const statePath = join(cache, 'state.json');
    const state = await readState(statePath);
    let output: HookOutput = {};
    if (start) {
      state.promptFingerprint = await fingerprint(root);
    } else {
      output = await validateStop(state, continued, {
        fingerprint: () => fingerprint(root),
        hasChanges: () => hasFrontendChanges(root),
        format: () => formatChangedFiles(root),
        lint: () => lintFrontend(root, join(cache, 'lint.log')),
        test: () => testFrontend(root, cache),
      });
    }
    await writeFile(statePath, JSON.stringify(state));
    process.stdout.write(JSON.stringify(output));
  } catch (error: unknown) {
    const reason = `Frontend validation hook failed: ${error instanceof Error ? error.message : String(error)}. Report validation as incomplete.`;
    if (start) {
      process.stderr.write(reason);
      process.exitCode = 1;
    } else {
      process.stdout.write(JSON.stringify(feedback(reason, continued)));
    }
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
