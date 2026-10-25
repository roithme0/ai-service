import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { backendProfile } from './backend.mts';
import { runCheck, runHook, type ValidationProfile } from './shared.mts';

const start = process.argv[2] === '--start';
const selection = process.argv[3] ?? '--all';
if (
  (!start && process.argv[2] !== '--stop') ||
  process.argv.length > 4 ||
  !['--all', '--frontend', '--backend'].includes(selection)
) {
  throw new Error(
    'Usage: node .codex/validation/run.mts --start|--stop [--all|--frontend|--backend]',
  );
}
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const profiles: ValidationProfile[] = [];
if (selection !== '--backend') {
  const { frontendProfile } = await import('./frontend.mts');
  profiles.push(frontendProfile(root));
}
if (selection !== '--frontend') profiles.push(backendProfile(root));
await runHook(root, profiles, start, async (cache) => {
  await runCheck(
    root,
    'Shared validation tests',
    ['--test', '.codex/validation/shared.test.mts'],
    join(cache, 'shared-tests.log'),
    120_000,
  );
});
