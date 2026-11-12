import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  parseValidationArguments,
  validate,
  type ValidationServices,
  type ValidationScope,
} from "./run.mts";
import type { ValidationProfile } from "./shared.mts";
import { parseTestArguments } from "./test.mts";

void test("validation uses full non-E2E selection independently of scope and rejects old flags", () => {
  const options = parseValidationArguments([
    "--scope",
    "frontend",
    "--no-format",
  ]);
  assert.equal(options.format, false);
  assert.equal(options.scope, "frontend");
  assert.ok(options.selection.groups.includes("backend"));
  assert.ok(!options.selection.groups.includes("e2e"));
  for (const flag of [
    "--app-tests",
    "--tooling-tests=false",
    "--shared-tooling-tests",
    "--e2e",
  ])
    assert.throws(() => parseValidationArguments([flag]), /removed.*--group/);
  assert.throws(
    () => parseValidationArguments(["--group", "backend", "--", "-q"]),
    /only by test/,
  );
});

void test("relevance runs full selection once and aggregate cache tracks both scopes", async () => {
  const root = await mkdtemp(join(tmpdir(), "validation-aggregate-"));
  const fingerprints: Record<string, string> = { frontend: "a", backend: "a" };
  const calls: string[] = [];
  const profiles: ValidationProfile[] = ["frontend", "backend"].map(
    (scope) => ({
      scope,
      policy: {
        label: scope,
        formatter: "formatter",
        success: "passed",
        retry: "retry",
      },
      dependencies: () => ({
        fingerprint: () => Promise.resolve(fingerprints[scope]),
        hasChanges: () => true,
        format: () => {
          calls.push(`format:${scope}`);
          return Promise.resolve({ checked: [], formatted: [] });
        },
        lint: () => {
          calls.push(`lint:${scope}`);
          return Promise.resolve();
        },
        test: () => Promise.resolve(),
      }),
    }),
  );
  const services: ValidationServices = {
    contracts: () => Promise.resolve(),
    profiles: (_root: string, scope: ValidationScope) =>
      Promise.resolve(
        profiles.filter(
          (profile) => scope === "all" || profile.scope === scope,
        ),
      ),
    tests: (_root, selection) => {
      calls.push(`tests:${selection.groups.join(",")}`);
      return Promise.resolve();
    },
  };
  const options = parseValidationArguments([]);
  const start = { sessionId: "session", start: true, continued: false };
  const stop = { ...start, start: false };
  assert.deepEqual(await validate(root, start, options, services), {});
  assert.deepEqual(await validate(root, stop, options, services), {});
  assert.deepEqual(calls, []);
  fingerprints["frontend"] = "b";
  assert.deepEqual(await validate(root, stop, options, services), {});
  assert.deepEqual(calls.slice(0, 2), ["format:frontend", "lint:frontend"]);
  assert.match(calls[2], /tooling-backend.*backend.*chat-ui-browser/);
  calls.length = 0;
  assert.deepEqual(await validate(root, stop, options, services), {});
  assert.deepEqual(calls, ["format:frontend"]);
  fingerprints["backend"] = "b";
  assert.deepEqual(await validate(root, stop, options, services), {});
  assert.ok(calls.join(" ").includes("tests:"));
});

async function aggregateFixture() {
  const root = await mkdtemp(join(tmpdir(), "aggregate-transitions-"));
  execFileSync("git", ["init", "-q"], { cwd: root });
  const fingerprints: Record<string, string> = {
    frontend: "initial",
    backend: "initial",
  };
  const calls: string[] = [];
  let failure = "";
  let changeDuringTests = false;
  let dirty = true;
  let formatted: string[] = [];
  const profiles: ValidationProfile[] = ["frontend", "backend"].map(
    (scope) => ({
      scope,
      policy: {
        label: scope,
        formatter: "formatter",
        success: "passed",
        retry: "retry",
      },
      dependencies: () => ({
        fingerprint: () => Promise.resolve(fingerprints[scope]),
        hasChanges: () => dirty,
        format: () => {
          calls.push(`format:${scope}`);
          if (failure === "format") throw new Error("format failed");
          return Promise.resolve({ checked: [], formatted });
        },
        lint: () => {
          calls.push(`lint:${scope}`);
          return Promise.resolve();
        },
        test: () => Promise.resolve(),
      }),
    }),
  );
  const services: ValidationServices = {
    contracts: () => {
      calls.push("contracts");
      if (failure === "contracts") throw new Error("contracts failed");
      return Promise.resolve();
    },
    profiles: (_root, scope) =>
      Promise.resolve(
        profiles.filter(
          (profile) => scope === "all" || profile.scope === scope,
        ),
      ),
    tests: () => {
      calls.push("tests");
      if (changeDuringTests) fingerprints["backend"] += "!";
      if (failure === "test") throw new Error("test failed");
      return Promise.resolve();
    },
  };
  return {
    root,
    fingerprints,
    calls,
    services,
    fail: (value: string) => {
      failure = value;
    },
    changeDuringTests: (value: boolean) => {
      changeDuringTests = value;
    },
    dirty: (value: boolean) => {
      dirty = value;
    },
    formatted: (value: string[]) => {
      formatted = value;
    },
  };
}

void test("aggregate validation orders checks, preserves retry, and never caches failures or concurrent edits", async () => {
  const f = await aggregateFixture();
  const options = parseValidationArguments([]);
  const start = { sessionId: "retry", start: true, continued: false };
  const stop = { ...start, start: false };
  await validate(f.root, start, options, f.services);
  f.fingerprints["frontend"] = "changed";
  f.fail("format");
  assert.equal(
    (await validate(f.root, stop, options, f.services)).failed,
    true,
  );
  assert.deepEqual(f.calls, ["format:frontend"]);
  f.calls.length = 0;
  f.fail("test");
  assert.equal(
    (await validate(f.root, { ...stop, continued: true }, options, f.services))
      .failed,
    true,
  );
  assert.deepEqual(f.calls, ["format:frontend", "lint:frontend", "contracts", "tests"]);
  f.calls.length = 0;
  f.fail("");
  f.changeDuringTests(true);
  assert.match(
    (await validate(f.root, { ...stop, continued: true }, options, f.services))
      .message ?? "",
    /changed during validation/,
  );
  f.calls.length = 0;
  f.changeDuringTests(false);
  assert.deepEqual(
    await validate(f.root, { ...stop, continued: true }, options, f.services),
    {},
  );
  assert.equal(f.calls.filter((call) => call === "tests").length, 1);
});
void test("missing snapshots honor dirty state and formatting reports changed files", async () => {
  const f = await aggregateFixture();
  const request = { sessionId: "missing", start: false, continued: false };
  f.dirty(false);
  assert.deepEqual(
    await validate(f.root, request, parseValidationArguments([]), f.services),
    {},
  );
  assert.deepEqual(f.calls, []);
  f.dirty(true);
  f.formatted(["frontend/source.ts"]);
  const result = await validate(
    f.root,
    request,
    parseValidationArguments(["--scope", "frontend"]),
    f.services,
  );
  assert.match(result.message ?? "", /frontend\/source\.ts/);
  assert.deepEqual(f.calls, ["format:frontend", "lint:frontend", "contracts", "tests"]);
});
void test("equivalent group selections reuse successful aggregate validation", async () => {
  const f = await aggregateFixture();
  const request = { sessionId: "normalized", start: false, continued: false };
  await validate(
    f.root,
    request,
    parseValidationArguments(["--group", "tooling", "--group", "backend"]),
    f.services,
  );
  f.calls.length = 0;
  await validate(
    f.root,
    request,
    parseValidationArguments([
      "--group",
      "backend",
      "--group",
      "tooling",
      "--group",
      "backend",
    ]),
    f.services,
  );
  assert.ok(!f.calls.includes("tests"));
});
void test("CI validation phases cover non-E2E and prebuilt E2E through the central selector", async () => {
  const workflow = await readFile(
    new URL("../../.github/workflows/publish-app.yml", import.meta.url),
    "utf8",
  );
  const commands = [
    ...workflow.matchAll(/run: node \.agents\/validation\/run\.mts([^\r\n]*)/g),
  ].map((match) => match[1].trim().split(/\s+/).filter(Boolean));
  assert.equal(commands.length, 3);
  const phases = commands.map(parseValidationArguments);
  assert.ok(phases.every((phase) => !phase.format));
  assert.deepEqual(
    phases[0].selection.groups,
    parseTestArguments(["--group", "non-e2e"]).groups,
  );
  assert.deepEqual(phases[1].selection.groups, ["evals"]);
  assert.equal(phases[1].omitContracts, false);
  assert.deepEqual(phases[2].selection.groups, ["e2e"]);
  assert.equal(phases[2].selection.prebuiltImages, true);
  assert.equal(phases[0].omitContracts, false);
  assert.equal(phases[2].omitContracts, true);
  assert.match(workflow, /pull_request:/);
  assert.match(workflow, /push:\s*\n\s*tags:/);
  assert.doesNotMatch(workflow, /npm run check:(conversation|transcription)-contract/);
  assert.match(workflow, /python -m venv \.venv/);
  assert.match(workflow, /\[test,dev\]/);
  assert.match(workflow, /evals:\s*\n\s*needs: validate/);
  const evalJob = workflow.split(/ {2}evals:\r?\n/)[1]?.split(/\r?\n {2}build-app:/)[0] ?? "";
  assert.match(evalJob, /node-version: ['"]24['"]/);
  assert.match(evalJob, /python-version: ['"]3\.13['"]/);
  assert.match(evalJob, /working-directory: backend[\s\S]*?pip install -e "\.\[test,dev\]"/);
  assert.match(evalJob, /working-directory: frontend\s*\n\s*run: npm ci/);
  assert.match(evalJob, /LIVE_DEMO_OPENAI_MODEL: \$\{\{ vars\.LIVE_DEMO_OPENAI_MODEL \|\| 'gpt-6-luna' \}\}/);
  assert.match(evalJob, /LIVE_DEMO_OPENAI_REASONING_EFFORT: \$\{\{ vars\.LIVE_DEMO_OPENAI_REASONING_EFFORT \|\| 'medium' \}\}/);
  assert.doesNotMatch(evalJob, /continue-on-error|pull_request_target|retry/i);
  assert.equal((evalJob.match(/^\s*if:/gm) ?? []).length, 1);
  assert.match(workflow, /if: failure\(\) && steps\.evaluation\.outcome == 'failure'/);
  assert.match(workflow, /name: evals-diagnostics[\s\S]*?path: \.codex-validation\/evals\/manual\/[\s\S]*?include-hidden-files: true[\s\S]*?retention-days: 7/);
  assert.equal((workflow.match(/OPENAI_API_KEY: \$\{\{ secrets\.OPENAI_API_KEY \}\}/g) ?? []).length, 2);
  assert.match(workflow, /build-app:\s*\n\s*needs: \[validate\]/);
  assert.match(workflow, /e2e:\s*\n\s*needs: build-app/);
  assert.match(workflow, /build-chat-ui:\s*\n\s*needs: e2e/);
  assert.match(
    workflow,
    /publish-app:\s*\n\s*needs: \[build-app, build-chat-ui, e2e, evals\]/,
  );
  assert.match(
    workflow,
    /publish-chat-ui:\s*\n\s*needs: \[build-app, build-chat-ui, e2e, evals\]/,
  );
});

void test("cache distinguishes partial selection, format state, session and forced runs", async () => {
  const f = await aggregateFixture();
  const full = parseValidationArguments([]);
  const partial = parseValidationArguments(["--group", "backend"]);
  const noFormat = parseValidationArguments(["--no-format"]);
  const request = { sessionId: "cache", start: false, continued: false };
  await validate(f.root, request, partial, f.services);
  f.calls.length = 0;
  await validate(f.root, request, full, f.services);
  assert.equal(f.calls.filter((call) => call === "tests").length, 1);
  f.calls.length = 0;
  await validate(f.root, request, noFormat, f.services);
  assert.ok(!f.calls.some((call) => call.startsWith("format:")));
  assert.equal(f.calls.filter((call) => call === "tests").length, 1);
  f.calls.length = 0;
  await validate(
    f.root,
    { ...request, sessionId: "other" },
    noFormat,
    f.services,
  );
  assert.equal(f.calls.filter((call) => call === "tests").length, 1);
  f.calls.length = 0;
  await validate(f.root, { ...request, force: true }, noFormat, f.services);
  assert.equal(f.calls.filter((call) => call === "tests").length, 1);
});

void test("freshness runs across scopes and selections and omitted runs cannot populate the cache", async () => {
  const f = await aggregateFixture();
  const request = { sessionId: "gate", start: false, continued: false };
  for (const args of [["--scope", "frontend", "--group", "backend"], ["--scope", "backend", "--group", "tooling"]]) {
    f.calls.length = 0;
    await validate(f.root, request, parseValidationArguments(args), f.services);
    assert.ok(f.calls.includes("contracts"));
  }
  assert.throws(() => parseValidationArguments(["--ci-prerequisite-contracts"]), /only for/);
  const omitted = parseValidationArguments(["--group", "e2e", "--ci-prerequisite-contracts"]);
  f.calls.length = 0;
  const actions = process.env["GITHUB_ACTIONS"];
  const job = process.env["GITHUB_JOB"];
  try {
    delete process.env["GITHUB_ACTIONS"];
    delete process.env["GITHUB_JOB"];
    assert.equal((await validate(f.root, { ...request, force: true }, omitted, f.services)).failed, true);
    process.env["GITHUB_ACTIONS"] = "true";
    process.env["GITHUB_JOB"] = "validate";
    assert.equal((await validate(f.root, { ...request, force: true }, omitted, f.services)).failed, true);
    process.env["GITHUB_JOB"] = "e2e";
    assert.equal((await validate(f.root, request, omitted, f.services)).failed, true);
    assert.deepEqual(await validate(f.root, { ...request, force: true }, omitted, f.services), {});
    assert.ok(!f.calls.includes("contracts"));
  } finally {
    if (actions === undefined) delete process.env["GITHUB_ACTIONS"]; else process.env["GITHUB_ACTIONS"] = actions;
    if (job === undefined) delete process.env["GITHUB_JOB"]; else process.env["GITHUB_JOB"] = job;
  }
  f.calls.length = 0;
  await validate(f.root, request, parseValidationArguments([]), f.services);
  assert.ok(f.calls.includes("contracts"));
  f.calls.length = 0;
  await validate(f.root, request, parseValidationArguments([]), f.services);
  assert.ok(!f.calls.includes("contracts"));
});

void test("freshness failure prevents tests and is never cached", async () => {
  const f = await aggregateFixture();
  const request = { sessionId: "gate-failure", start: false, continued: false };
  f.fail("contracts");
  const failed = await validate(f.root, request, parseValidationArguments([]), f.services);
  assert.equal(failed.failed, true);
  assert.match(failed.message ?? "", /contracts failed/);
  assert.ok(!f.calls.includes("tests"));
  f.fail("");
  f.calls.length = 0;
  await validate(f.root, { ...request, continued: true }, parseValidationArguments([]), f.services);
  assert.ok(f.calls.includes("contracts"));
  assert.ok(f.calls.includes("tests"));
});

void test("explicit evals run on snapshots only after start and always rerun", async () => {
  const f = await aggregateFixture();
  const options = parseValidationArguments(["--group", "evals"]);
  const request = { sessionId: "eval-fresh", start: true, continued: false };
  await validate(f.root, request, options, f.services);
  assert.ok(!f.calls.includes("tests"));
  await validate(f.root, { ...request, start: false }, options, f.services);
  await validate(f.root, { ...request, start: false }, options, f.services);
  assert.equal(f.calls.filter((call) => call === "tests").length, 2);
});
