import assert from "node:assert/strict";
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
  assert.deepEqual(f.calls, ["format:frontend", "lint:frontend", "tests"]);
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
  assert.deepEqual(f.calls, ["format:frontend", "lint:frontend", "tests"]);
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
  assert.equal(commands.length, 2);
  const phases = commands.map(parseValidationArguments);
  assert.ok(phases.every((phase) => !phase.format));
  assert.deepEqual(
    phases[0].selection.groups,
    parseTestArguments(["--group", "non-e2e"]).groups,
  );
  assert.deepEqual(phases[1].selection.groups, ["e2e"]);
  assert.equal(phases[1].selection.prebuiltImages, true);
  assert.match(workflow, /python -m venv \.venv/);
  assert.match(workflow, /\[test,dev\]/);
  assert.match(workflow, /build-app:\s*\n\s*needs: \[validate\]/);
  assert.match(workflow, /e2e:\s*\n\s*needs: build-app/);
  assert.match(
    workflow,
    /publish-app:\s*\n\s*needs: \[build-app, build-chat-ui, e2e\]/,
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
