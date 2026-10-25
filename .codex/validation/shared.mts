import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { lstat, mkdir, readFile, realpath, writeFile } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve } from 'node:path';

export interface FormatResult {
  checked: string[];
  formatted: string[];
}

export interface PendingFormatting {
  path: string;
  name: string;
  original: string;
  formatted: string;
}

export interface ValidationState {
  promptFingerprint?: string;
  successfulFingerprint?: string;
  pendingValidation?: boolean;
}

export interface ValidationDependencies {
  fingerprint: () => Promise<string>;
  hasChanges: () => boolean;
  format: () => Promise<FormatResult>;
  lint?: () => Promise<void>;
  test: () => Promise<void>;
}

export interface HookOutput {
  decision?: 'block';
  reason?: string;
  systemMessage?: string;
}

export interface ValidationPolicy {
  label: string;
  formatter: string;
  success: string;
  retry: string;
}

export interface ValidationProfile {
  scope: string;
  policy: ValidationPolicy;
  dependencies: (cache: string) => ValidationDependencies;
}

export function git(root: string, args: string[]): string[] {
  return execFileSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true })
    .split('\0')
    .filter(Boolean);
}

export async function fingerprint(
  root: string,
  inputs: string[],
  extraPaths: string[] = [],
): Promise<string> {
  const paths = git(root, [
    'ls-files',
    '--cached',
    '--others',
    '--exclude-standard',
    '-z',
    '--',
    ...inputs,
  ]);
  paths.push(...extraPaths);
  const hash = createHash('sha256').update(process.version);
  for (const name of [...new Set(paths)].sort()) {
    hash.update(name).update('\0');
    try {
      const content = await readFile(join(root, name));
      hash.update(String(content.length)).update('\0').update(content);
    } catch (error: unknown) {
      if (!(error instanceof Error && 'code' in error && error.code === 'ENOENT')) throw error;
      hash.update('missing');
    }
    hash.update('\0');
  }
  return hash.digest('hex');
}

export function changedFiles(root: string, scope: string): string[] {
  const conflicts = git(root, ['diff', '--name-only', '-z', '--diff-filter=U', '--', scope]);
  if (conflicts.length > 0) {
    throw new Error(`Resolve ${scope} merge conflicts before formatting: ${conflicts.join(', ')}`);
  }
  const diffArgs = ['--name-only', '-z', '--diff-filter=ACMR', '--', scope];
  const staged = git(root, ['diff', '--cached', ...diffArgs]);
  const unstaged = git(root, ['diff', ...diffArgs]);
  const untracked = git(root, ['ls-files', '--others', '--exclude-standard', '-z', '--', scope]);
  return [...new Set([...staged, ...unstaged, ...untracked])].sort();
}

export async function sourcePath(
  root: string,
  scope: string,
  name: string,
): Promise<string | null> {
  const path = resolve(root, name);
  const stat = await lstat(path).catch((error: unknown) => {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') return null;
    throw error;
  });
  if (!stat?.isFile() || stat.isSymbolicLink()) return null;
  const within = relative(join(root, scope), await realpath(path));
  if (isAbsolute(within) || within.startsWith('..')) {
    throw new Error(`Refusing to format a path outside ${scope}: ${name}`);
  }
  return path;
}

export async function writeFormatting(pending: PendingFormatting[]): Promise<string[]> {
  const formatted: string[] = [];
  for (const file of pending) {
    if ((await readFile(file.path, 'utf8')) !== file.original) {
      throw new Error(`File changed during formatting; retry after edits finish: ${file.name}`);
    }
    await writeFile(file.path, file.formatted);
    formatted.push(file.name);
  }
  return formatted;
}

export async function runCheck(
  cwd: string,
  label: string,
  args: string[],
  logPath: string,
  timeout: number,
  executable: string = process.execPath,
  input?: string,
): Promise<string> {
  const result = spawnSync(executable, args, {
    cwd,
    encoding: 'utf8',
    timeout,
    maxBuffer: 8 * 1024 * 1024,
    windowsHide: true,
    input,
  });
  const output = [result.stdout, result.stderr, result.error?.message].filter(Boolean).join('\n');
  await writeFile(logPath, output);
  if (result.status !== 0) {
    throw new Error(`${label} failed. Full report: ${logPath}\n${output.slice(-16_000)}`);
  }
  return result.stdout;
}

function feedback(reason: string, continued: boolean): HookOutput {
  return continued ? { systemMessage: reason } : { decision: 'block', reason };
}

export async function validateStop(
  state: ValidationState,
  continued: boolean,
  dependencies: ValidationDependencies,
  policy: ValidationPolicy,
): Promise<HookOutput> {
  let formattedFiles: string[] = [];
  try {
    const before = await dependencies.fingerprint();
    if (
      (state.promptFingerprint === before && (!continued || !state.pendingValidation)) ||
      (!state.promptFingerprint && !dependencies.hasChanges())
    )
      return {};
    state.pendingValidation = true;
    const formatting = await dependencies.format();
    formattedFiles = formatting.formatted;
    const current = await dependencies.fingerprint();
    if (current !== state.successfulFingerprint) {
      await dependencies.lint?.();
      await dependencies.test();
      if ((await dependencies.fingerprint()) !== current) {
        throw new Error(
          `${policy.label} files changed during validation. Run validation again after edits finish.`,
        );
      }
      state.successfulFingerprint = current;
    }
    if (formattedFiles.length === 0) {
      state.pendingValidation = false;
      return {};
    }
    return feedback(
      `${policy.formatter} formatted: ${formattedFiles.join(', ')}. Review the diff before completing. Do not undo formatting. ${policy.success}`,
      continued,
    );
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    const notice = formattedFiles.length
      ? `${policy.formatter} formatted: ${formattedFiles.join(', ')}. Review the diff; do not undo formatting.\n`
      : '';
    return feedback(
      `${notice}${message}\nFix findings in your changes and rerun ${policy.retry}. Do not perform a broad existing-debt cleanup without authorization. If blocked by existing debt or dependencies, report validation as incomplete and explain why; do not claim it passed.`,
      continued,
    );
  }
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
      pendingValidation: 'pendingValidation' in state && state.pendingValidation === true,
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

export async function runHook(
  root: string,
  profiles: ValidationProfile[],
  start: boolean,
  checkShared?: (cache: string) => Promise<void>,
): Promise<void> {
  let continued = false;
  try {
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
    continued = 'stop_hook_active' in input && input.stop_hook_active === true;
    const session = createHash('sha256').update(input.session_id).digest('hex');
    const outputs: HookOutput[] = [];
    let sharedTests: Promise<void> | undefined;
    for (const profile of profiles) {
      try {
        const cache = join(root, profile.scope, '.codex-validation', session);
        await mkdir(cache, { recursive: true });
        const statePath = join(cache, 'state.json');
        const state = await readState(statePath);
        const dependencies = profile.dependencies(cache);
        const testScope = dependencies.test;
        dependencies.test = async () => {
          if (checkShared) {
            sharedTests ??= checkShared(cache);
            await sharedTests;
          }
          await testScope();
        };
        if (start) state.promptFingerprint = await dependencies.fingerprint();
        else outputs.push(await validateStop(state, continued, dependencies, profile.policy));
        await writeFile(statePath, JSON.stringify(state));
      } catch (error: unknown) {
        const reason = `${profile.policy.label} validation hook failed: ${error instanceof Error ? error.message : String(error)}. Report validation as incomplete.`;
        if (start) throw new Error(reason, { cause: error });
        outputs.push(feedback(reason, continued));
      }
    }
    const reasons = outputs.flatMap((output) =>
      output.reason ? [output.reason] : output.systemMessage ? [output.systemMessage] : [],
    );
    process.stdout.write(
      JSON.stringify(reasons.length ? feedback(reasons.join('\n\n'), continued) : {}),
    );
  } catch (error: unknown) {
    const reason = `Validation hook failed: ${error instanceof Error ? error.message : String(error)}. Report validation as incomplete.`;
    if (start) {
      process.stderr.write(reason);
      process.exitCode = 1;
    } else process.stdout.write(JSON.stringify(feedback(reason, continued)));
  }
}
