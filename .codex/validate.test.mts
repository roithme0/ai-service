import assert from "node:assert/strict";
import { spawnSync, type SpawnSyncReturns } from "node:child_process";
import { join } from "node:path";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { hookOutput, hookRequest, parseHookArguments } from "./validate.mts";

void test("Codex adapter accepts hook modes and optional validation scopes", () => {
  for (const mode of ["--start", "--stop"]) {
    const start = mode === "--start";
    assert.deepEqual(parseHookArguments([mode]), { start, scope: "all" });
    for (const scope of ["all", "frontend", "backend"]) {
      assert.deepEqual(parseHookArguments([mode, `--${scope}`]), {
        start,
        scope,
      });
    }
  }
});

void test("Codex adapter rejects missing, unknown, and extra arguments", () => {
  for (const args of [
    [],
    ["--unknown"],
    ["--stop", "--unknown"],
    ["--stop", "--all", "--frontend"],
  ]) {
    assert.throws(() => parseHookArguments(args), /Usage:/);
  }
});

void test("Codex adapter normalizes requests and bounds continuation feedback", () => {
  assert.deepEqual(hookRequest({ session_id: "fixture" }, true), {
    sessionId: "fixture",
    start: true,
    continued: false,
  });
  assert.deepEqual(
    hookRequest({ session_id: "fixture", stop_hook_active: true }, false),
    {
      sessionId: "fixture",
      start: false,
      continued: true,
    },
  );
  assert.throws(
    () => hookRequest({ session_id: "fixture" }, false),
    /stop_hook_active/,
  );
  assert.deepEqual(hookOutput({}, false), {});
  assert.deepEqual(hookOutput({ message: "failed" }, false), {
    decision: "block",
    reason: "failed",
  });
  assert.deepEqual(hookOutput({ message: "failed" }, true), {
    systemMessage: "failed",
  });
  assert.deepEqual(
    hookOutput({ message: "Formatted source.ts. Review the diff." }, false),
    {
      decision: "block",
      reason: "Formatted source.ts. Review the diff.",
    },
  );
});

function invoke(mode: string, input: unknown): SpawnSyncReturns<string> {
  const root = mkdtempSync(join(tmpdir(), "adapter-test-"));
  execFileSync("git", ["init", "-q", root]);
  const script = join(root, "adapter.mjs");
  const module = new URL("./validate.mts", import.meta.url).href;
  writeFileSync(
    script,
    `import { parseHookArguments, runHook } from ${JSON.stringify(module)}; await runHook(parseHookArguments([${JSON.stringify(mode)}]), ${JSON.stringify(root)});`,
  );
  return spawnSync(process.execPath, [script], {
    cwd: root,
    encoding: "utf8",
    windowsHide: true,
    input: JSON.stringify(input),
  });
}

void test("Codex adapter dispatches snapshots and skips validation on an unchanged turn", () => {
  const input = {
    session_id: `adapter-test-${process.pid}`,
    stop_hook_active: false,
  };
  const root = mkdtempSync(join(tmpdir(), "adapter-session-"));
  execFileSync("git", ["init", "-q", root]);
  const script = join(root, "adapter.mjs");
  const module = new URL("./validate.mts", import.meta.url).href;
  for (const mode of ["--start", "--stop"]) {
    writeFileSync(
      script,
      `import { parseHookArguments, runHook } from ${JSON.stringify(module)}; await runHook(parseHookArguments([${JSON.stringify(mode)}]), ${JSON.stringify(root)});`,
    );
    const result = spawnSync(process.execPath, [script], {
      cwd: root,
      encoding: "utf8",
      input: JSON.stringify(input),
    });
    assert.equal(result.status, 0, String(result.stderr));
    assert.equal(result.stdout, "{}");
  }
});

void test("Codex adapter reports malformed input without silently passing validation", () => {
  const start = invoke("--start", {});
  assert.equal(start.status, 1);
  assert.match(String(start.stderr), /Expected Codex session_id/);
  const stop = invoke("--stop", {});
  assert.equal(stop.status, 0);
  const output = JSON.parse(stop.stdout) as {
    decision?: string;
    reason?: string;
  };
  assert.equal(output.decision, "block");
  assert.match(output.reason ?? "", /Expected Codex session_id/);
});
