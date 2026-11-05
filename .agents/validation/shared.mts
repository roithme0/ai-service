import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { lstat, readFile, realpath, writeFile } from 'node:fs/promises';
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

export interface ValidationDependencies {
  reuseSuccess?: boolean;
  fingerprint: () => Promise<string>;
  hasChanges: () => boolean;
  format: () => Promise<FormatResult>;
  lint?: () => Promise<void>;
  test: () => Promise<void>;
}

export interface ValidationFeedback {
  message?: string;
  failed?: boolean;
}

export interface ValidationRequest {
  sessionId: string;
  start: boolean;
  continued: boolean;
  force?: boolean;
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
  return execFileSync('git', args, {
    cwd: root,
    encoding: 'utf8',
    windowsHide: true,
  })
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
  env?: NodeJS.ProcessEnv,
): Promise<string> {
  const result = spawnSync(executable, args, {
    cwd,
    encoding: 'utf8',
    timeout,
    maxBuffer: 8 * 1024 * 1024,
    windowsHide: true,
    input,
    env,
  });
  const output = [result.stdout, result.stderr, result.error?.message].filter(Boolean).join('\n');
  await writeFile(logPath, output);
  if (result.status !== 0) {
    throw new Error(`${label} failed. Full report: ${logPath}\n${output.slice(-16_000)}`);
  }
  return result.stdout;
}
