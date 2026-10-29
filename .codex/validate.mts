import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describeChecks, validate } from '../.agents/validation/run.mts';
import type {
  ValidationChecks,
  ValidationFeedback,
  ValidationRequest,
} from '../.agents/validation/shared.mts';

export interface HookOutput {
  decision?: 'block';
  reason?: string;
  systemMessage?: string;
}

export const hookChecks: Readonly<ValidationChecks> = {
  appTests: true,
  toolingTests: true,
  sharedToolingTests: true,
  e2e: false,
};

interface HookArguments {
  start: boolean;
  scope: 'all' | 'frontend' | 'backend';
}

export function hookOutput({ message }: ValidationFeedback, continued: boolean): HookOutput {
  if (!message) return {};
  if (continued) return { systemMessage: message };
  return { decision: 'block', reason: message };
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

export function parseHookArguments(args: readonly string[]): HookArguments {
  const [mode, selection = '--all'] = args;
  if (
    (mode !== '--start' && mode !== '--stop') ||
    args.length > 2 ||
    (selection !== '--all' && selection !== '--frontend' && selection !== '--backend')
  )
    throw new Error('Usage: node .codex/validate.mts --start|--stop [--all|--frontend|--backend]');

  const scope =
    selection === '--frontend' ? 'frontend' : selection === '--backend' ? 'backend' : 'all';
  return { start: mode === '--start', scope };
}

function writeHookOutput(feedback: ValidationFeedback, continued: boolean): void {
  process.stdout.write(JSON.stringify(hookOutput(feedback, continued)));
}

async function runHook({ start, scope }: HookArguments): Promise<void> {
  let continued = false;
  try {
    const request = hookRequest(JSON.parse(readFileSync(0, 'utf8')) as unknown, start);
    continued = request.continued;
    process.stderr.write(`${describeChecks({ scope, checks: hookChecks })}\n`);
    const result = await validate(resolve(dirname(fileURLToPath(import.meta.url)), '..'), request, {
      scope,
      checks: hookChecks,
    });
    writeHookOutput(result, continued);
  } catch (error: unknown) {
    const message = `Validation hook failed: ${error instanceof Error ? error.message : String(error)}. Report validation as incomplete.`;
    if (start) {
      process.stderr.write(message);
      process.exitCode = 1;
    } else writeHookOutput({ message }, continued);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await runHook(parseHookArguments(process.argv.slice(2)));
}
