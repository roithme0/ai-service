import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validate } from '../.agents/validation/run.mts';
import type { ValidationFeedback, ValidationRequest } from '../.agents/validation/shared.mts';

export interface HookOutput {
  decision?: 'block';
  reason?: string;
  systemMessage?: string;
}

export function hookOutput({ message }: ValidationFeedback, continued: boolean): HookOutput {
  return !message
    ? {}
    : continued
      ? { systemMessage: message }
      : { decision: 'block', reason: message };
}

export function hookRequest(input: unknown, start: boolean): ValidationRequest {
  if (
    typeof input !== 'object' ||
    input === null ||
    !('session_id' in input) ||
    typeof input.session_id !== 'string' ||
    (!start && (!('stop_hook_active' in input) || typeof input.stop_hook_active !== 'boolean'))
  )
    throw new Error('Expected Codex session_id and, for Stop, boolean stop_hook_active.');
  return {
    sessionId: input.session_id,
    start,
    continued: 'stop_hook_active' in input && input.stop_hook_active === true,
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const mode = process.argv[2];
  const selection = process.argv[3] ?? '--all';
  if (
    !['--start', '--stop'].includes(mode) ||
    process.argv.length > 4 ||
    !['--all', '--frontend', '--backend'].includes(selection)
  )
    throw new Error('Usage: node .codex/validate.mts --start|--stop [--all|--frontend|--backend]');
  const start = mode === '--start';
  let continued = false;
  try {
    const request = hookRequest(JSON.parse(readFileSync(0, 'utf8')) as unknown, start);
    continued = request.continued;
    const scope =
      selection === '--frontend' ? 'frontend' : selection === '--backend' ? 'backend' : 'all';
    const result = await validate(
      resolve(dirname(fileURLToPath(import.meta.url)), '..'),
      request,
      scope,
    );
    process.stdout.write(JSON.stringify(hookOutput(result, continued)));
  } catch (error: unknown) {
    const message = `Validation hook failed: ${error instanceof Error ? error.message : String(error)}. Report validation as incomplete.`;
    if (start) {
      process.stderr.write(message);
      process.exitCode = 1;
    } else process.stdout.write(JSON.stringify(hookOutput({ message }, continued)));
  }
}
