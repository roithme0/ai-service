import assert from 'node:assert/strict';
import { spawnSync, type SpawnSyncReturns } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { hookOutput, hookRequest } from './validate.mts';

void test('Codex adapter normalizes requests and bounds continuation feedback', () => {
  assert.deepEqual(hookRequest({ session_id: 'fixture' }, true), {
    sessionId: 'fixture',
    start: true,
    continued: false,
  });
  assert.deepEqual(hookRequest({ session_id: 'fixture', stop_hook_active: true }, false), {
    sessionId: 'fixture',
    start: false,
    continued: true,
  });
  assert.throws(() => hookRequest({ session_id: 'fixture' }, false), /stop_hook_active/);
  assert.deepEqual(hookOutput({}, false), {});
  assert.deepEqual(hookOutput({ message: 'failed' }, false), {
    decision: 'block',
    reason: 'failed',
  });
  assert.deepEqual(hookOutput({ message: 'failed' }, true), { systemMessage: 'failed' });
});

function invoke(mode: string, input: unknown): SpawnSyncReturns<string> {
  return spawnSync(
    process.execPath,
    [fileURLToPath(new URL('./validate.mts', import.meta.url)), mode],
    {
      cwd: resolve(dirname(fileURLToPath(import.meta.url)), '..'),
      encoding: 'utf8',
      windowsHide: true,
      input: JSON.stringify(input),
    },
  );
}

void test('Codex adapter dispatches snapshots and skips validation on an unchanged turn', () => {
  const input = { session_id: `adapter-test-${process.pid}`, stop_hook_active: false };
  for (const mode of ['--start', '--stop']) {
    const result = invoke(mode, input);
    assert.equal(result.status, 0, String(result.stderr));
    assert.equal(result.stdout, '{}');
  }
});

void test('Codex adapter reports malformed input without silently passing validation', () => {
  const start = invoke('--start', {});
  assert.equal(start.status, 1);
  assert.match(String(start.stderr), /Expected Codex session_id/);
  const stop = invoke('--stop', {});
  assert.equal(stop.status, 0);
  const output = JSON.parse(stop.stdout) as { decision?: string; reason?: string };
  assert.equal(output.decision, 'block');
  assert.match(output.reason ?? '', /Expected Codex session_id/);
});
