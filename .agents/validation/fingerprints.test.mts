import assert from "node:assert/strict";
import { test } from "node:test";
import { execFileSync } from "node:child_process";
import { mkdtemp, mkdir, rename, readFile, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fingerprint, frontendProfile } from "./frontend.mts";
import { e2eProfile } from "./e2e.mts";
import { backendProfile, backendPython } from "./backend.mts";
import {
  parseValidationArguments,
  validate,
  type ValidationServices,
} from "./run.mts";

function git(root: string, args: string[]): string {
  return execFileSync("git", args, { cwd: root, encoding: "utf8" });
}

void test("contract source, outputs, dependencies, policy and installed environments affect aggregate inputs", async () => {
  const root = await mkdtemp(join(tmpdir(), "contract-inputs-"));
  execFileSync("git", ["init", "-q"], { cwd: root });
  const profiles = [frontendProfile(root), backendProfile(root)].map((profile) => profile.dependencies(root));
  let previous = await Promise.all(profiles.map((profile) => profile.fingerprint()));
  const python = backendPython(root);
  const paths: [string, number[]][] = [
    ["backend/app/api/conversation.py", [1]],
    ["backend/scripts/export_openapi.py", [1]],
    ["backend/pyproject.toml", [1]],
    ["frontend/scripts/contract-generator.mjs", [0]],
    ["frontend/scripts/conversation-contract.mjs", [0]],
    ["frontend/package-lock.json", [0]],
    ["frontend/projects/chat-ui/conversation/src/generated.ts", [0]],
    [".agents/validation/contracts.mts", [0, 1]],
    ["frontend/node_modules/.package-lock.json", [0]],
    ["backend/.venv/pyvenv.cfg", [1]],
    [python.slice(root.length + 1), [1]],
  ];
  for (const [path, affected] of paths) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), "changed");
    const current = await Promise.all(profiles.map((profile) => profile.fingerprint()));
    for (const index of affected) assert.notEqual(current[index], previous[index], path);
    previous = current;
  }
  await unlink(join(root, "frontend/projects/chat-ui/conversation/src/generated.ts"));
  assert.notEqual(await profiles[0].fingerprint(), previous[0]);
});

void test("shared validation and Codex adapter changes invalidate every validation scope", async () => {
  const root = await mkdtemp(join(tmpdir(), "ai-service-validation-scopes-"));
  execFileSync("git", ["init", "-q"], { cwd: root });
  const profiles = [
    frontendProfile(root).dependencies(root),
    backendProfile(root).dependencies(root),
    e2eProfile(root).dependencies(root),
  ];
  let previous = await Promise.all(
    profiles.map((profile) => profile.fingerprint()),
  );
  for (const name of [".agents/validation/shared.mts", ".codex/validate.mts"]) {
    await mkdir(dirname(join(root, name)), { recursive: true });
    await writeFile(join(root, name), "changed");
    const current = await Promise.all(
      profiles.map((profile) => profile.fingerprint()),
    );
    for (let index = 0; index < profiles.length; index++) {
      assert.notEqual(current[index], previous[index]);
      assert.equal(profiles[index].hasChanges(), true);
    }
    previous = current;
  }
});

void test("end-to-end scope includes backend and gateway edits without expanding frontend unit scope", async () => {
  const root = await mkdtemp(join(tmpdir(), "ai-service-e2e-"));
  execFileSync("git", ["init", "-q"], { cwd: root });
  const dependencies = e2eProfile(root).dependencies(root);
  const unitFingerprint = await fingerprint(root);
  let previous = await dependencies.fingerprint();
  assert.equal(dependencies.hasChanges(), false);
  for (const name of [
    "backend/app/main.py",
    "deployment/gateway/nginx.conf",
    "frontend/e2e/test.spec.ts",
  ]) {
    await mkdir(dirname(join(root, name)), { recursive: true });
    await writeFile(join(root, name), "changed");
    assert.equal(dependencies.hasChanges(), true);
    const current = await dependencies.fingerprint();
    assert.notEqual(current, previous);
    previous = current;
    if (!name.startsWith("frontend/"))
      assert.equal(await fingerprint(root), unitFingerprint);
  }
  await mkdir(join(root, "docs"));
  await writeFile(join(root, "docs/notes.md"), "documentation");
  assert.equal(await dependencies.fingerprint(), previous);
  assert.equal(dependencies.reuseSuccess, false);
});

void test("selected E2E detects deployment edits during execution", async () => {
  const root = await mkdtemp(join(tmpdir(), "ai-service-e2e-concurrent-"));
  execFileSync("git", ["init", "-q"], { cwd: root });
  const deployment = join(root, "deployment/docker-compose-local.yml");
  await mkdir(dirname(deployment), { recursive: true });
  await writeFile(deployment, "before");
  const services: ValidationServices = {
    contracts: () => Promise.resolve(),
    profiles: () =>
      Promise.resolve([
        {
          scope: "frontend",
          policy: {
            label: "frontend",
            formatter: "formatter",
            success: "passed",
            retry: "retry",
          },
          dependencies: () => ({
            fingerprint: () => Promise.resolve("unchanged"),
            hasChanges: () => true,
            format: () => Promise.resolve({ checked: [], formatted: [] }),
            test: () => Promise.resolve(),
          }),
        },
      ]),
    tests: async () => {
      await writeFile(deployment, "during");
    },
  };
  const result = await validate(
    root,
    { sessionId: "e2e", start: false, continued: false },
    parseValidationArguments(["--no-format", "--group", "e2e"]),
    services,
  );
  assert.equal(result.failed, true);
  assert.match(result.message ?? "", /changed during validation/);
});

void test("fingerprints include new, changed, renamed, and deleted inputs but exclude caches", async () => {
  const root = await mkdtemp(join(tmpdir(), "ai-service-lint-"));
  const frontend = join(root, "frontend");
  await mkdir(join(frontend, ".angular/cache"), { recursive: true });
  await mkdir(join(frontend, ".codex-validation"), { recursive: true });
  await writeFile(
    join(frontend, ".gitignore"),
    ".angular/cache/\n.codex-validation/\n",
  );
  await writeFile(join(frontend, "source.ts"), "export const value = 1;");
  execFileSync("git", ["init", "-q"], { cwd: root });
  execFileSync("git", ["add", "frontend/source.ts"], { cwd: root });
  const initial = await fingerprint(root);
  await writeFile(join(frontend, ".angular/cache/state.json"), "{}");
  await writeFile(join(frontend, ".codex-validation/state.json"), "{}");
  await mkdir(join(root, ".agents/.codex-validation"), { recursive: true });
  await writeFile(
    join(root, ".agents/.gitignore"),
    await readFile(new URL("../../.agents/.gitignore", import.meta.url)),
  );
  for (const scope of ["frontend", "backend", "e2e"]) {
    const path = `.agents/.codex-validation/${scope}/state.json`;
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), "{}");
    assert.equal(git(root, ["check-ignore", path]).trim(), path);
  }
  assert.equal(await fingerprint(root), initial);
  await writeFile(join(frontend, "source.ts"), "export const value = 2;");
  const edited = await fingerprint(root);
  assert.notEqual(edited, initial);
  await writeFile(join(frontend, "new.ts"), "export const added = true;");
  const added = await fingerprint(root);
  assert.notEqual(added, edited);
  await rename(join(frontend, "source.ts"), join(frontend, "renamed.ts"));
  assert.notEqual(await fingerprint(root), added);
});
