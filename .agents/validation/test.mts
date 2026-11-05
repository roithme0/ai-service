import { mkdir, readdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { backendPython, runBackendPytest } from './backend.mts';
import { runCheck } from './shared.mts';

export const toolingFiles = {
  'tooling-shared': ['.agents/validation/shared.test.mts', '.agents/validation/run.test.mts', '.agents/validation/fingerprints.test.mts', '.agents/validation/contracts.test.mts', '.agents/validation/test.test.mts', '.codex/validate.test.mts'],
  'tooling-frontend': ['.agents/validation/frontend.test.mts', 'frontend/scripts/contract-comparison.test.mjs'],
  'tooling-backend': ['.agents/validation/backend.test.mts'],
  'tooling-contracts': ['frontend/scripts/transcription-contract.test.mjs'],
  'tooling-e2e': ['.agents/validation/e2e.test.mts'],
} as const;

export const groupDescriptions = {
  'tooling-shared': 'Shared orchestration, selection, fingerprints and adapter',
  'tooling-frontend': 'Frontend formatting, lint and comparison tooling',
  'tooling-backend': 'Backend validation and formatter tooling',
  'tooling-contracts': 'Generated transcription contract assertions',
  'tooling-e2e': 'Mocked E2E orchestration and readiness',
  backend: 'Backend pytest suite',
  'frontend-app': 'Angular application tests',
  'chat-ui': 'Chat UI unit and component tests',
  'chat-ui-browser': 'Chat UI browser component tests',
  e2e: 'Docker-backed application flow',
} as const;
export type TestGroup = keyof typeof groupDescriptions;
const groups = Object.keys(groupDescriptions) as TestGroup[];
const tooling = Object.keys(toolingFiles) as TestGroup[];
const aliases: Readonly<Record<string, readonly TestGroup[]>> = {
  tooling, 'non-e2e': groups.filter((group) => group !== 'e2e'), all: groups,
};
export interface TestSelection { groups: TestGroup[]; nativeArgs: string[]; prebuiltImages: boolean; list: boolean }

export function parseTestArguments(args: readonly string[], allowNative = true): TestSelection {
  const chosen = new Set<TestGroup>();
  let selected = false;
  let prebuiltImages = false;
  let list = false;
  let nativeArgs: string[] = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === '--') {
      if (!allowNative) throw new Error('Native runner arguments are supported only by test.mts.');
      nativeArgs = args.slice(i + 1);
      if (!nativeArgs.length) throw new Error('Expected native runner arguments after --.');
      break;
    }
    if (arg === '--group' || arg.startsWith('--group=')) {
      const value = arg === '--group' ? args[++i] : arg.slice('--group='.length);
      if (!value || value.startsWith('--')) throw new Error('Expected a group name after --group.');
      const expanded = aliases[value] ?? (groups.includes(value as TestGroup) ? [value as TestGroup] : undefined);
      if (!expanded) throw new Error(`Unknown test group: ${value}`);
      selected = true;
      for (const group of expanded) chosen.add(group);
    } else if (arg === '--list') list = true;
    else if (arg === '--prebuilt-images') prebuiltImages = true;
    else throw new Error(`Unknown test option: ${arg}`);
  }
  const resolved = groups.filter((group) => selected ? chosen.has(group) : group !== 'e2e');
  if (nativeArgs.length && (resolved.length !== 1 || !selected)) throw new Error('Native arguments require exactly one concrete group.');
  if (prebuiltImages && !resolved.includes('e2e')) throw new Error('--prebuilt-images requires selecting e2e.');
  const boundary = nativeArgs.indexOf('--');
  const group = resolved[0];
  if (boundary !== -1 && group in toolingFiles) {
    const files = nativeArgs.slice(boundary + 1);
    if (!files.length) throw new Error('Expected tooling test paths after the native -- separator.');
    const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
    const allowed = toolingFiles[group as keyof typeof toolingFiles].map((file) => resolve(root, file));
    if (files.some((file) => !allowed.includes(resolve(root, file)))) throw new Error(`Native tooling paths must belong to ${group}.`);
  }
  return { groups: resolved, nativeArgs, prebuiltImages, list };
}

export async function assertToolingMembership(root: string): Promise<void> {
  const registered: string[] = Object.values(toolingFiles).flat();
  const found: string[] = [];
  for (const [dir, suffix] of [['.agents/validation', '.test.mts'], ['.codex', '.test.mts'], ['frontend/scripts', '.test.mjs']] as const) {
    for (const entry of await readdir(join(root, dir), { withFileTypes: true })) {
      if (entry.isFile() && entry.name.endsWith(suffix)) found.push(`${dir}/${entry.name}`);
    }
  }
  const duplicate = registered.filter((file, i) => registered.indexOf(file) !== i);
  const missing = registered.filter((file) => !found.includes(file));
  const unregistered = found.filter((file) => !registered.includes(file));
  if (duplicate.length || missing.length || unregistered.length) throw new Error(`Invalid tooling registry: duplicate [${duplicate.join(', ')}], missing [${missing.join(', ')}], unregistered [${unregistered.join(', ')}]`);
}

export async function runTests(root: string, selection: TestSelection, run: typeof runCheck = runCheck): Promise<void> {
  const cache = join(root, '.agents/.codex-validation/tests/manual');
  await mkdir(cache, { recursive: true });
  for (const group of selection.groups) {
    const log = join(cache, `${group}.log`);
    if (group in toolingFiles) {
      const explicitFiles = selection.nativeArgs.includes('--');
      await run(root, group, ['--test', ...selection.nativeArgs, ...(explicitFiles ? [] : toolingFiles[group as keyof typeof toolingFiles])], log, 120_000);
    } else if (group === 'backend') {
      await runBackendPytest(root, cache, backendPython(root), run, selection.nativeArgs);
    } else if (group === 'e2e') {
      const { testE2E } = await import('./e2e.mts');
      await testE2E(root, join(root, '.agents/.codex-validation/e2e/manual'), run, selection.prebuiltImages, selection.nativeArgs);
    } else {
      const frontend = join(root, 'frontend');
      const project = group === 'frontend-app' ? 'ai-service-frontend' : 'chat-ui';
      await run(frontend, group, [join(frontend, 'node_modules/@angular/cli/bin/ng.js'), 'test', project, ...(group === 'chat-ui-browser' ? ['--configuration', 'browser'] : []), '--watch=false', ...selection.nativeArgs], log, 300_000);
    }
  }
}

export function describeSelection(selection: TestSelection): string {
  return `Tests: ${selection.groups.join(', ')}; ${selection.nativeArgs.length ? 'selective native arguments' : 'complete groups'}${selection.prebuiltImages ? '; prebuilt images' : ''}.`;
}
export async function runTestCommand(root: string, args: readonly string[]): Promise<number> {
  try {
    const selection = parseTestArguments(args);
    if (selection.list) {
      for (const group of groups) process.stdout.write(`${group}: ${groupDescriptions[group]}\n`);
      for (const alias of Object.keys(aliases)) process.stdout.write(`${alias}: group alias\n`);
      return 0;
    }
    process.stdout.write(`${describeSelection(selection)}\n`);
    await runTests(root, selection);
    return 0;
  } catch (error: unknown) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await runTestCommand(resolve(dirname(fileURLToPath(import.meta.url)), '../..'), process.argv.slice(2));
}
