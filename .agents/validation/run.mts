import { randomUUID } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { backendProfile } from './backend.mts';
import { e2eProfile } from './e2e.mts';
import {
  runCheck,
  runValidation,
  defaultChecks,
  type ValidationChecks,
  type ValidationFeedback,
  type ValidationProfile,
  type ValidationRequest,
} from './shared.mts';

export type ValidationScope = 'all' | 'frontend' | 'backend';

export interface ValidationArguments {
  scope: ValidationScope;
  checks: Readonly<ValidationChecks>;
}

const checkFlags: ReadonlyMap<string, keyof ValidationChecks> = new Map([
  ['--app-tests', 'appTests'],
  ['--tooling-tests', 'toolingTests'],
  ['--shared-tooling-tests', 'sharedToolingTests'],
  ['--e2e', 'e2e'],
]);

export function parseValidationArguments(args: readonly string[]): ValidationArguments {
  let scope: ValidationScope = 'all';
  const checks = { ...defaultChecks };
  const seen = new Set<string>();
  for (let index = 0; index < args.length; index += 1) {
    const [flag, inline, extra] = args[index].split('=');
    if (extra !== undefined) throw new Error(`Invalid validation option: ${args[index]}`);
    if (seen.has(flag)) throw new Error(`Repeated validation option: ${flag}`);
    seen.add(flag);
    if (flag === '--scope') {
      const value = inline ?? args[++index];
      if (value !== 'all' && value !== 'frontend' && value !== 'backend') {
        throw new Error('Expected --scope all|frontend|backend.');
      }
      scope = value;
      continue;
    }
    const key = checkFlags.get(flag);
    if (!key || (inline !== undefined && inline !== 'true' && inline !== 'false')) {
      throw new Error(`Unknown validation option or invalid boolean: ${args[index]}`);
    }
    checks[key] = inline !== 'false';
  }
  return { scope, checks };
}

export function describeChecks({ scope, checks }: ValidationArguments): string {
  const selected = scope === 'backend' ? ['format'] : ['format', 'lint'];
  const skipped: string[] = [];
  for (const [flag, key] of checkFlags) {
    (checks[key] ? selected : skipped).push(flag.slice(2));
  }
  return `Validation (${scope}): selected ${selected.join(', ')}; skipped ${skipped.join(', ') || 'none'}.`;
}

async function runSharedTests(root: string, cache: string): Promise<void> {
  await runCheck(
    root,
    'Shared validation tests',
    ['--test', '.agents/validation/shared.test.mts', '.agents/validation/run.test.mts'],
    join(cache, 'shared-tests.log'),
    120_000,
  );
}

export async function validationProfiles(
  root: string,
  { scope = 'all', checks = defaultChecks }: Partial<ValidationArguments> = {},
): Promise<ValidationProfile[]> {
  const profiles: ValidationProfile[] = [];
  if (scope !== 'backend') {
    const { frontendProfile } = await import('./frontend.mts');
    profiles.push(frontendProfile(root, checks));
  }
  if (scope !== 'frontend') profiles.push(backendProfile(root, checks));
  if (checks.e2e) profiles.push(e2eProfile(root));
  return profiles;
}

export async function validate(
  root: string,
  request: ValidationRequest,
  { scope = 'all', checks = defaultChecks }: Partial<ValidationArguments> = {},
): Promise<ValidationFeedback> {
  const profiles = await validationProfiles(root, { scope, checks });
  return runValidation(root, profiles, request, {
    checkShared: checks.sharedToolingTests
      ? (cache: string) => runSharedTests(root, cache)
      : undefined,
    checks,
  });
}

export async function runValidationCommand(
  root: string,
  args: readonly string[],
  run: typeof validate = validate,
): Promise<number> {
  try {
    const options = parseValidationArguments(args);
    process.stdout.write(`${describeChecks(options)}\n`);
    const result = await run(
      root,
      { sessionId: `manual-${randomUUID()}`, start: false, continued: false, force: true },
      options,
    );
    if (result.message) {
      process.stderr.write(`${result.message}\n`);
    }
    if (!result.failed) process.stdout.write('Selected validation checks passed.\n');
    return result.failed ? 1 : 0;
  } catch (error: unknown) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await runValidationCommand(
    resolve(dirname(fileURLToPath(import.meta.url)), '../..'),
    process.argv.slice(2),
  );
}
