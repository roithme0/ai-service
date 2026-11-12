import assert from "node:assert/strict";
import { test } from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  assertToolingMembership,
  groupDescriptions,
  parseTestArguments,
  runTests,
  toolingFiles,
} from "./test.mts";
import { runCheck } from "./shared.mts";

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
    all.filter((group) => group !== "e2e" && group !== "evals"),
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
    all.filter((group) => group !== "evals"),
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
  await runTests(fixture, parseTestArguments(["--group", "image-generation-browser"]), run);
  assert.deepEqual(calls[2]?.args.slice(1), ["test", "image-generation", "--configuration", "browser", "--watch=false"]);
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

void test("eval selection is explicit, deduplicated and rejects native arguments", () => {
  for (const selection of [[], ["--group", "non-e2e"], ["--group", "tooling"]]) {
    assert.ok(!parseTestArguments(selection).groups.includes("evals"));
  }
  const all = parseTestArguments(["--group", "all", "--group", "evals"]);
  assert.ok(all.groups.includes("e2e"));
  assert.equal(all.groups.filter((group) => group === "evals").length, 1);
  assert.throws(() => parseTestArguments(["--group", "evals", "--", "--help"]), /not supported for evals/);
});

void test("evaluation uses unique reports and propagates runner failures", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "eval-run-"));
  const calls: { cwd: string; args: string[]; log: string; executable?: string }[] = [];
  const run: typeof runCheck = (cwd, _label, args, log, _timeout, executable) => {
    calls.push({ cwd, args, log, executable });
    return Promise.resolve("evaluation evidence\n");
  };
  const selection = parseTestArguments(["--group", "evals", "--group", "evals"]);
  await runTests(fixture, selection, run);
  await runTests(fixture, selection, run);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].cwd, fixture);
  assert.deepEqual(calls[0].args.slice(0, 3), ["-m", "app.evals.conversation_tool_use", "--report"]);
  assert.notEqual(calls[0].args[3], calls[1].args[3]);
  assert.equal(dirname(calls[0].args[3]), dirname(calls[0].log));
  assert.ok(calls[0].executable?.includes(".venv"));
  await assert.rejects(runTests(fixture, selection, () => Promise.reject(new Error("runner failed"))), /runner failed/);
});

void test("evaluation process failures retain current logs and propagate", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "eval-fail-"));
  const selection = parseTestArguments(["--group", "evals"]);
  for (const status of [1, 2]) {
    let logPath = "";
    const run: typeof runCheck = (cwd, label, _args, log, timeout) => {
      logPath = log;
      return runCheck(cwd, label, ["-e", `process.stdout.write('status ${status} evidence'); process.exit(${status})`], log, timeout);
    };
    await assert.rejects(runTests(fixture, selection, run), new RegExp(`status ${status} evidence`));
    assert.match(await readFile(logPath, "utf8"), new RegExp(`status ${status} evidence`));
  }
  const startup: typeof runCheck = (cwd, label, _args, log, timeout) =>
    runCheck(cwd, label, [], log, timeout, join(fixture, "missing-python"));
  await assert.rejects(runTests(fixture, selection, startup), /evals failed/);
});

void test("successful evaluation surfaces the report location and evaluator evidence", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "eval-output-"));
  const originalWrite = Object.getOwnPropertyDescriptor(process.stdout, "write");
  let output = "";
  try {
    process.stdout.write = (chunk: string | Uint8Array) => {
      output += chunk.toString();
      return true;
    };
    await runTests(fixture, parseTestArguments(["--group", "evals"]), () =>
      Promise.resolve("passed; model example; greetings__greet name=Anna outcome=success\n"),
    );
  } finally {
    if (originalWrite) Object.defineProperty(process.stdout, "write", originalWrite);
    else Reflect.deleteProperty(process.stdout, "write");
  }
  assert.match(output, /Evaluation report: .*report\.json/);
  assert.match(output, /passed; model example; greetings__greet name=Anna outcome=success/);
});

void test("evaluation timeout propagates and preserves available diagnostics", async () => {
  const fixture = await mkdtemp(join(tmpdir(), "eval-timeout-"));
  let logPath = "";
  const run: typeof runCheck = (cwd, label, _args, log) => {
    logPath = log;
    return runCheck(cwd, label, ["-e", "setInterval(() => {}, 1000)"], log, 100);
  };
  await assert.rejects(runTests(fixture, parseTestArguments(["--group", "evals"]), run), /evals failed/);
  assert.match(await readFile(logPath, "utf8"), /ETIMEDOUT|timed out/i);
});
