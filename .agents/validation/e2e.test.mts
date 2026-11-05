import assert from "node:assert/strict";
import { test } from "node:test";
import {
  copyFile,
  mkdtemp,
  mkdir,
  readFile,
  readdir,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createServer } from "node:http";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { testE2E, waitForGateway } from "./e2e.mts";
import type { runCheck } from "./shared.mts";

void test("direct E2E wrapper reports invalid selector arguments without starting checks", () => {
  const script = fileURLToPath(new URL("./e2e.mts", import.meta.url));
  const result = spawnSync(process.execPath, [script, "--invalid-option"], {
    encoding: "utf8",
    windowsHide: true,
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Unknown test option: --invalid-option/);
});

void test("direct E2E wrapper dispatches without an import cycle", async () => {
  const root = await mkdtemp(join(tmpdir(), "e2e-wrapper-"));
  const source = dirname(fileURLToPath(import.meta.url));
  const destination = join(root, ".agents/validation");
  await mkdir(destination, { recursive: true });
  for (const file of await readdir(source)) {
    if (file.endsWith(".mts") && !file.endsWith(".test.mts"))
      await copyFile(join(source, file), join(destination, file));
  }
  const result = spawnSync(process.execPath, [join(destination, "e2e.mts")], {
    encoding: "utf8",
    windowsHide: true,
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /missing installed Playwright dependency/);
});

void test("missing Playwright fails before any Docker command", async () => {
  const root = await mkdtemp(join(tmpdir(), "ai-service-e2e-prerequisites-"));
  const run: typeof runCheck = () => {
    assert.fail("Docker must not run without Playwright installed");
  };
  await assert.rejects(
    testE2E(root, join(root, "cache"), run),
    /Incomplete E2E validation: missing installed Playwright dependency/,
  );
});

void test("E2E runs isolate artifacts from other runs and the shared Playwright output", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "ai-service-e2e-artifacts-"));
  const cli = join(root, "frontend/node_modules/@playwright/test/cli.js");
  await mkdir(dirname(cli), { recursive: true });
  await writeFile(cli, "");
  const shared = join(root, "frontend/e2e/test-results");
  await mkdir(shared, { recursive: true });
  await writeFile(join(shared, "trace.zip"), "shared trace");
  t.mock.method(globalThis, "fetch", () =>
    Promise.resolve(new Response("ready")),
  );
  const outputs: string[] = [];
  const reports: string[] = [];
  const run: typeof runCheck = async (
    _cwd,
    label,
    args,
    _log,
    _timeout,
    _command,
    _input,
    env,
  ) => {
    if (label === "Playwright") {
      assert.deepEqual(args.slice(0, 3), [cli, "test", "--output"]);
      const output = args[3];
      assert.ok(output);
      outputs.push(output);
      await mkdir(output, { recursive: true });
      await writeFile(join(output, "trace.zip"), output);
      const report = env?.["PLAYWRIGHT_HTML_OUTPUT_DIR"];
      assert.ok(report);
      assert.equal(dirname(report), dirname(output));
      assert.notEqual(report, output);
      assert.equal(env?.["PLAYWRIGHT_HTML_OPEN"], "never");
      reports.push(report);
      await mkdir(report, { recursive: true });
      await writeFile(join(report, "index.html"), report);
    }
    return "";
  };
  const cache = join(root, "cache");
  await Promise.all([testE2E(root, cache, run), testE2E(root, cache, run)]);
  assert.equal(outputs.length, 2);
  assert.notEqual(outputs[0], outputs[1]);
  for (const output of outputs) {
    assert.equal(dirname(dirname(output)), cache);
    assert.equal(await readFile(join(output, "trace.zip"), "utf8"), output);
  }
  assert.equal(reports.length, 2);
  assert.notEqual(reports[0], reports[1]);
  for (const report of reports) {
    assert.equal(await readFile(join(report, "index.html"), "utf8"), report);
  }
  assert.equal(
    await readFile(join(shared, "trace.zip"), "utf8"),
    "shared trace",
  );
});

void test("E2E collects diagnostics for Docker and Playwright failures and preserves the original error", async (t) => {
  t.mock.method(globalThis, "fetch", () =>
    Promise.resolve(new Response("ready")),
  );
  for (const failure of [
    "Docker availability",
    "Docker build and startup",
    "Gateway restart",
    "Playwright",
  ]) {
    for (const diagnosticsFail of [false, true]) {
      const root = await mkdtemp(join(tmpdir(), "ai-service-e2e-diagnostics-"));
      const cli = join(root, "frontend/node_modules/@playwright/test/cli.js");
      await mkdir(dirname(cli), { recursive: true });
      await writeFile(cli, "");
      const cache = join(root, "cache");
      const original = new Error(failure);
      const calls: Parameters<typeof runCheck>[] = [];
      const run: typeof runCheck = async (...args) => {
        calls.push(args);
        if (args[1] === failure) throw original;
        if (args[1] === "E2E failure diagnostics") {
          if (diagnosticsFail) throw new Error("diagnostic command failed");
          await writeFile(args[3], "diagnostic output");
        }
        return "";
      };
      await assert.rejects(
        testE2E(root, cache, run),
        (error: unknown) => error === original,
      );
      assert.equal(calls[0][1], "Docker availability");
      assert.deepEqual(calls[0][2], ["info", "--format", "{{.ServerVersion}}"]);
      const diagnostics = calls.filter(
        (args) => args[1] === "E2E failure diagnostics",
      );
      assert.deepEqual(
        diagnostics.map((args) => args[2]),
        [
          [
            "compose",
            "-f",
            "deployment/docker-compose-local.yml",
            "ps",
            "--all",
          ],
          [
            "compose",
            "-f",
            "deployment/docker-compose-local.yml",
            "logs",
            "--no-color",
            "--tail",
            "2000",
          ],
        ],
      );
      for (const args of diagnostics) {
        assert.equal(args[5], "docker");
        assert.equal(args[7]?.["GATEWAY_PORT"], calls[0][7]?.["GATEWAY_PORT"]);
      }
      for (const name of ["services", "services-logs"]) {
        const report = await readFile(
          join(cache, `${name}${diagnosticsFail ? "-error" : ""}.log`),
          "utf8",
        );
        assert.match(
          report,
          diagnosticsFail ? /diagnostic command failed/ : /diagnostic output/,
        );
      }
    }
  }
});

void test("prebuilt E2E uses loaded images without building or pulling app images", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "ai-service-e2e-prebuilt-"));
  const cli = join(root, "frontend/node_modules/@playwright/test/cli.js");
  await mkdir(dirname(cli), { recursive: true });
  await writeFile(cli, "");
  t.mock.method(globalThis, "fetch", () =>
    Promise.resolve(new Response("ready")),
  );
  const compose = [
    "compose",
    "-f",
    "deployment/docker-compose-local.yml",
    "-f",
    "deployment/docker-compose-e2e.override.yml",
  ];
  for (const fail of [false, true]) {
    const calls: Parameters<typeof runCheck>[] = [];
    const original = new Error("startup failed");
    const run: typeof runCheck = (...args) => {
      calls.push(args);
      if (fail && args[1] === "Docker build and startup") throw original;
      return Promise.resolve("");
    };
    const result = testE2E(root, join(root, "cache"), run, true);
    if (fail)
      await assert.rejects(result, (error: unknown) => error === original);
    else await result;
    const commands = calls
      .filter((args) => args[2][0] === "compose")
      .map((args) => args[2]);
    assert.deepEqual(commands, [
      [...compose, "pull", "gateway"],
      [
        ...compose,
        "up",
        "-d",
        "--no-build",
        "--pull",
        "never",
        "--wait",
        "--wait-timeout",
        "60",
      ],
      ...(fail
        ? [
            [...compose, "ps", "--all"],
            [...compose, "logs", "--no-color", "--tail", "2000"],
          ]
        : [[...compose, "restart", "gateway"]]),
    ]);
    assert.equal(
      calls.some((args) => args[1] === "Playwright"),
      !fail,
    );
  }
});

void test("gateway readiness retries startup errors and requires both frontend and backend", async () => {
  const paths: string[] = [];
  let backendRequests = 0;
  let unavailable = false;
  const server = createServer((request, response) => {
    paths.push(request.url ?? "");
    if (request.url === "/api/openapi.json") backendRequests++;
    response.statusCode = unavailable
      ? 503
      : request.url === "/api/openapi.json" && backendRequests < 2
        ? 502
        : 200;
    response.end();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    const baseURL = `http://127.0.0.1:${address.port}`;
    await waitForGateway(baseURL, 5_000);
    assert.deepEqual(paths, [
      "/",
      "/api/openapi.json",
      "/",
      "/api/openapi.json",
    ]);
    unavailable = true;
    await assert.rejects(
      waitForGateway(baseURL, 0),
      /did not become ready.*HTTP 503/,
    );
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
});
