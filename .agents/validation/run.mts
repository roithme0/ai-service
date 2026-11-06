import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { backendProfile } from './backend.mts';
import { frontendProfile } from './frontend.mts';
import { e2eProfile } from './e2e.mts';
import { checkContracts } from './contracts.mts';
import { describeSelection, groupDescriptions, parseTestArguments, runTests, type TestSelection } from './test.mts';
import type { ValidationFeedback, ValidationProfile, ValidationRequest } from './shared.mts';

export type ValidationScope = 'all' | 'frontend' | 'backend';
export interface ValidationArguments { scope: ValidationScope; format: boolean; selection: TestSelection; omitContracts?: boolean }

export function parseValidationArguments(args: readonly string[]): ValidationArguments {
  let scope: ValidationScope = 'all';
  let format = true;
  let seenScope = false;
  let omitContracts = false;
  const testArgs: string[] = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (/^--(?:app-tests|tooling-tests|shared-tooling-tests|e2e)(?:=|$)/.test(arg)) throw new Error(`Legacy option ${arg} was removed; use --group NAME (or --group e2e).`);
    if (arg === '--scope' || arg.startsWith('--scope=')) {
      if (seenScope) throw new Error('Repeated --scope.');
      seenScope = true;
      const value = arg === '--scope' ? args[++i] : arg.slice('--scope='.length);
      if (value !== 'all' && value !== 'frontend' && value !== 'backend') throw new Error('Expected --scope all|frontend|backend.');
      scope = value;
    } else if (arg === '--no-format') format = false;
    else if (arg === '--ci-prerequisite-contracts') omitContracts = true;
    else testArgs.push(arg);
  }
  const selection = parseTestArguments(testArgs, false);
  if (omitContracts && (selection.groups.length !== 1 || selection.groups[0] !== 'e2e')) throw new Error('--ci-prerequisite-contracts is only for the downstream CI E2E phase after prerequisite validation.');
  return { scope, format, selection, omitContracts };
}
export function describeChecks(options: ValidationArguments): string {
  return `Validation (${options.scope}): ${options.format ? 'format, ' : ''}lint, ${options.omitContracts ? 'contracts omitted (CI prerequisite)' : 'paired contract freshness'}. ${describeSelection(options.selection)}`;
}

interface State { prompts?: Record<string, string>; pending?: string[]; successful?: string }
async function readState(path: string): Promise<State> {
  try {
    const value: unknown = JSON.parse(await readFile(path, 'utf8'));
    if (typeof value !== 'object' || value === null) return {};
    const state = value as State;
    return state;
  } catch (error: unknown) {
    if (error instanceof SyntaxError || (error instanceof Error && 'code' in error && error.code === 'ENOENT')) return {};
    throw error;
  }
}
function hash(value: unknown): string { return createHash('sha256').update(JSON.stringify(value)).digest('hex'); }
export function validationProfiles(root: string, scope: ValidationScope): Promise<ValidationProfile[]> {
  return Promise.resolve([frontendProfile(root), backendProfile(root)].filter((profile) => scope === 'all' || profile.scope === scope));
}
export interface ValidationServices {
  profiles: (root: string, scope: ValidationScope) => Promise<ValidationProfile[]>;
  tests: typeof runTests;
  contracts?: typeof checkContracts;
}
export async function validate(root: string, request: ValidationRequest, options: ValidationArguments, services: ValidationServices = { profiles: validationProfiles, tests: runTests }): Promise<ValidationFeedback> {
  if (options.omitContracts && (!request.force || process.env['GITHUB_ACTIONS'] !== 'true' || process.env['GITHUB_JOB'] !== 'e2e')) {
    return { failed: true, message: '--ci-prerequisite-contracts is restricted to the GitHub Actions downstream E2E job after prerequisite validation.' };
  }
  const session = hash(request.sessionId);
  const cache = join(root, '.agents/.codex-validation/aggregate-v2', session);
  await mkdir(cache, { recursive: true });
  const path = join(cache, 'state.json');
  const state = await readState(path);
  const profiles = await services.profiles(root, options.scope);
  const allProfiles = await services.profiles(root, 'all');
  const deps = new Map(allProfiles.map((profile) => [profile.scope, profile.dependencies(join(cache, profile.scope))]));
  for (const profile of allProfiles) await mkdir(join(cache, profile.scope), { recursive: true });
  const fingerprints = async (): Promise<Record<string, string>> => {
    const result = Object.fromEntries(await Promise.all(allProfiles.map(async (profile) => [profile.scope, await deps.get(profile.scope)!.fingerprint()] as const)));
    if (options.selection.groups.includes('e2e')) result['e2e'] = await e2eProfile(root).dependencies(cache).fingerprint();
    return result;
  };
  const formatted: string[] = [];
  try {
    const before = await fingerprints();
    if (request.start) {
      state.prompts = { ...state.prompts, ...Object.fromEntries(profiles.map((profile) => [profile.scope, before[profile.scope]])) };
      await writeFile(path, JSON.stringify(state));
      return {};
    }
    const relevant = profiles.filter((profile) => {
      const dep = deps.get(profile.scope)!;
      return request.force || (request.continued && state.pending?.includes(profile.scope)) || (state.prompts?.[profile.scope] ? state.prompts[profile.scope] !== before[profile.scope] : dep.hasChanges());
    });
    if (!relevant.length) return {};
    state.pending = relevant.map((profile) => profile.scope);
    await writeFile(path, JSON.stringify(state));
    if (options.format) for (const profile of relevant) formatted.push(...(await deps.get(profile.scope)!.format()).formatted);
    const current = await fingerprints();
    const identity = hash(['aggregate-v3-paired-contracts', relevant.map((profile) => profile.scope), options.format, true, options.selection.groups, current]);
    if (request.force || options.selection.groups.includes('e2e') || identity !== state.successful) {
      state.successful = undefined;
      await writeFile(path, JSON.stringify(state));
      for (const profile of relevant) await deps.get(profile.scope)!.lint?.();
      if (!options.omitContracts) await (services.contracts ?? checkContracts)(root, join(cache, 'contracts'));
      await services.tests(root, options.selection);
      if (hash(await fingerprints()) !== hash(current)) throw new Error('Files changed during validation. Run validation again after edits finish.');
      if (!options.omitContracts) state.successful = identity;
    }
    state.pending = [];
    await writeFile(path, JSON.stringify(state));
    return formatted.length ? { message: `Formatted: ${formatted.join(', ')}. Review the diff before completing. Selected validation checks passed.` } : {};
  } catch (error: unknown) {
    if (request.start) throw error;
    return { failed: true, message: `${formatted.length ? `Formatted: ${formatted.join(', ')}. Review the diff.\n` : ''}${error instanceof Error ? error.message : String(error)}\nFix findings and rerun node .agents/validation/run.mts. If blocked, report validation as incomplete.` };
  }
}
export async function runValidationCommand(root: string, args: readonly string[], run: typeof validate = validate): Promise<number> {
  try {
    const options = parseValidationArguments(args);
    if (options.selection.list) {
      for (const [name, description] of Object.entries(groupDescriptions)) process.stdout.write(`${name}: ${description}\n`);
      process.stdout.write('tooling: group alias\nnon-e2e: group alias\nall: group alias\n');
      return 0;
    }
    process.stdout.write(`${describeChecks(options)}\n`);
    const result = await run(root, { sessionId: `manual-${randomUUID()}`, start: false, continued: false, force: true }, options);
    if (result.message) process.stderr.write(`${result.message}\n`);
    if (!result.failed) process.stdout.write('Selected validation checks passed.\n');
    return result.failed ? 1 : 0;
  } catch (error: unknown) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await runValidationCommand(resolve(dirname(fileURLToPath(import.meta.url)), '../..'), process.argv.slice(2));
