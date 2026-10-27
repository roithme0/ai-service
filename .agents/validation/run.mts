import { join } from 'node:path';
import { backendProfile } from './backend.mts';
import { e2eProfile } from './e2e.mts';
import {
  runCheck,
  runValidation,
  type ValidationFeedback,
  type ValidationProfile,
  type ValidationRequest,
} from './shared.mts';

export async function validate(
  root: string,
  request: ValidationRequest,
  selection: 'all' | 'frontend' | 'backend' = 'all',
): Promise<ValidationFeedback> {
  const profiles: ValidationProfile[] = [];
  if (selection !== 'backend') {
    const { frontendProfile } = await import('./frontend.mts');
    profiles.push(frontendProfile(root));
  }
  if (selection !== 'frontend') profiles.push(backendProfile(root));
  profiles.push(e2eProfile(root));
  return runValidation(root, profiles, request, async (cache) => {
    await runCheck(
      root,
      'Shared validation tests',
      ['--test', '.agents/validation/shared.test.mts'],
      join(cache, 'shared-tests.log'),
      120_000,
    );
  });
}
