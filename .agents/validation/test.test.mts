import assert from "node:assert/strict";
import { test } from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  assertToolingMembership,
  groupDescriptions,
  parseTestArguments,
  runTests,
  toolingFiles,
} from "./test.mts";
import type { runCheck } from "./shared.mts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
void test("registry covers the bounded tooling directories", async () => {
  await assertToolingMembership(root);
});
void test("aliases normalize and invalid forwarding fails", () => {
  assert.deepEqual(
    parseTestArguments(["--group", "tooling", "--group", "tooling-shared"])
      .groups,
    parseTestArguments(["--group", "tooling"]).groups,
  );
  for (const args of [
    ["--group"],
    ["--group", "unknown"],
    ["--"],
    ["--group", "tooling", "--", "--test-name-pattern=x"],
    ["--prebuilt-images"],
  ]) {
    assert.throws(() => parseTestArguments(args));
  }
});
void test("single tooling group forwards Node options before files", async () => {
  const calls: string[][] = [];
  const run: typeof runCheck = (_cwd, _label, args) => {
    calls.push(args);
    return Promise.resolve("");
  };
  await runTests(
    root,
    parseTestArguments([
      "--group",
      "tooling-contracts",
      "--",
      "--test-name-pattern=generated",
    ]),
    run,
  );
  assert.deepEqual(calls[0], [
    "--test",
    "--test-name-pattern=generated",
    "frontend/scripts/transcription-contract.test.mjs",
  ]);
});
void test("native tooling file selection does not append the whole group", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "tooling-file-"));
  const calls: string[][] = [];
  const run: typeof runCheck = (_cwd, _label, args) => {
    calls.push(args);
    return Promise.resolve("");
  };
  await runTests(
    fixture,
    parseTestArguments([
      "--group",
      "tooling-shared",
      "--",
      "--test-name-pattern=cache",
      "--",
      ".agents/validation/run.test.mts",
    ]),
    run,
  );
  assert.deepEqual(calls[0], [
    "--test",
    "--test-name-pattern=cache",
    "--",
    ".agents/validation/run.test.mts",
  ]);
});
void test("native tooling file selection rejects paths outside the selected group", () => {
  assert.throws(
    () =>
      parseTestArguments([
        "--group",
        "tooling-shared",
        "--",
        "--",
        "frontend/scripts/transcription-contract.test.mjs",
      ]),
    /belong to tooling-shared/i,
  );
  assert.throws(
    () =>
      parseTestArguments([
        "--group",
        "tooling-shared",
        "--",
        "--test-name-pattern=x",
        "--",
      ]),
    /file|path/i,
  );
});
void test("native option values resembling test paths retain registered files", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "tooling-pattern-"));
  for (const nativeArgs of [
    ["--test-name-pattern=example.test.mts"],
    ["--test-name-pattern", "example.test.mts"],
    ["--import", "./setup.test.mts"],
    ["--require", "./setup.test.mjs"],
  ]) {
    const calls: string[][] = [];
    const run: typeof runCheck = (_cwd, _label, args) => {
      calls.push(args);
      return Promise.resolve("");
    };
    await runTests(
      fixture,
      parseTestArguments(["--group", "tooling-contracts", "--", ...nativeArgs]),
      run,
    );
    assert.deepEqual(calls[0], [
      "--test",
      ...nativeArgs,
      "frontend/scripts/transcription-contract.test.mjs",
    ]);
  }
});
void test("default and combined aliases select every intended family exactly once in canonical order", () => {
  const all = Object.keys(groupDescriptions);
  assert.deepEqual(
    parseTestArguments([]).groups,
    all.filter((group) => group !== "e2e"),
  );
  assert.deepEqual(
    parseTestArguments([
      "--group",
      "e2e",
      "--group",
      "non-e2e",
      "--group",
      "tooling",
    ]).groups,
    all,
  );
  assert.deepEqual(
    parseTestArguments(["--group", "all", "--group", "all"]).groups,
    all,
  );
});
void test("invalid selections and forwarding are rejected", () => {
  for (const args of [
    ["--group="],
    ["--group", "--list"],
    ["--unknown"],
    ["--group", "backend", "--"],
    ["--group", "backend", "--group", "frontend-app", "--", "filter"],
    ["--group", "backend", "--prebuilt-images"],
  ])
    assert.throws(() => parseTestArguments(args));
  assert.throws(() =>
    parseTestArguments(["--group", "backend", "--", "filter"], false),
  );
  assert.equal(
    parseTestArguments(["--group", "e2e", "--prebuilt-images"]).prebuiltImages,
    true,
  );
});
void test("membership scan detects unexpected and missing files but ignores nested scenarios", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "tooling-membership-"));
  for (const file of Object.values(toolingFiles).flat()) {
    await mkdir(dirname(join(fixture, file)), { recursive: true });
    await writeFile(join(fixture, file), "");
  }
  await mkdir(join(fixture, ".agents/validation/scenarios"), {
    recursive: true,
  });
  await writeFile(
    join(fixture, ".agents/validation/scenarios/ignored.test.mts"),
    "",
  );
  await assertToolingMembership(fixture);
  await writeFile(join(fixture, ".codex/unregistered.test.mts"), "");
  await assert.rejects(
    assertToolingMembership(fixture),
    /unregistered.*\.codex\/unregistered\.test\.mts/,
  );
  const empty = await mkdtemp(join(tmpdir(), "tooling-missing-"));
  for (const dir of [".agents/validation", ".codex", "frontend/scripts"])
    await mkdir(join(empty, dir), { recursive: true });
  await assert.rejects(
    assertToolingMembership(empty),
    /missing.*shared\.test\.mts/,
  );
});
void test("selected runners receive their working directory and native arguments, and failures propagate", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "test-runners-"));
  const calls: {
    cwd: string;
    args: string[];
    executable: string | undefined;
  }[] = [];
  const run: typeof runCheck = (
    cwd,
    _label,
    args,
    _log,
    _timeout,
    executable,
  ) => {
    calls.push({ cwd, args, executable });
    return Promise.resolve("");
  };
  await runTests(
    fixture,
    parseTestArguments(["--group", "backend", "--", "-k", "example"]),
    run,
  );
  assert.equal(calls[0]?.cwd, join(fixture, "backend"));
  assert.deepEqual(calls[0]?.args.slice(0, 2), ["-m", "pytest"]);
  assert.match(calls[0]?.args[2] ?? "", /^--basetemp=/);
  assert.equal(calls[0]?.args[3], "-o");
  assert.match(calls[0]?.args[4] ?? "", /^cache_dir=/);
  assert.deepEqual(calls[0]?.args.slice(5), ["-k", "example"]);
  assert.ok(
    calls[0]?.executable?.startsWith(join(fixture, "backend", ".venv")),
  );
  await runTests(
    fixture,
    parseTestArguments([
      "--group",
      "chat-ui-browser",
      "--",
      "--include=example",
    ]),
    run,
  );
  assert.equal(calls[1]?.cwd, join(fixture, "frontend"));
  assert.deepEqual(calls[1]?.args.slice(1), [
    "test",
    "chat-ui",
    "--configuration",
    "browser",
    "--watch=false",
    "--include=example",
  ]);
  const fail: typeof runCheck = () =>
    Promise.reject(new Error("runner failed"));
  await assert.rejects(
    runTests(
      fixture,
      parseTestArguments(["--group", "tooling-frontend"]),
      fail,
    ),
    /runner failed/,
  );
});
