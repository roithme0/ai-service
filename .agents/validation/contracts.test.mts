import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { backendPython } from "./backend.mts";
import { checkContracts } from "./contracts.mts";
import type { runCheck } from "./shared.mts";

async function fixture(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "contract-gate-"));
  await mkdir(dirname(backendPython(root)), { recursive: true });
  await writeFile(backendPython(root), "");
  await mkdir(join(root, "frontend/node_modules/@hey-api/openapi-ts"), { recursive: true });
  return root;
}

void test("freshness checks all capabilities using the repository interpreter", async () => {
  const root = await fixture();
  const calls: Parameters<typeof runCheck>[] = [];
  const run: typeof runCheck = (...args) => { calls.push(args); return Promise.resolve(""); };
  await checkContracts(root, join(root, "cache"), run);
  assert.equal(calls.length, 4);
  assert.equal(calls[0][5], backendPython(root));
  assert.match(calls[0][2][1], /sys\.exit/);
  assert.doesNotMatch(calls[0][2][1], /\bassert\b/);
  for (const [index, capability] of ["conversation", "transcription", "image-generation"].entries()) {
    const call = calls[index + 1];
    assert.match(call[1], new RegExp(capability));
    assert.deepEqual(call[2], [join(root, `frontend/scripts/${capability}-contract.mjs`), "--check"]);
    assert.equal(call[7]?.["PYTHON"], backendPython(root));
  }
});

void test("missing prerequisites and capability failures propagate actionable guidance", async () => {
  const missing = await mkdtemp(join(tmpdir(), "contract-missing-"));
  await assert.rejects(checkContracts(missing, join(missing, "cache")), /backend\/\.venv Python 3\.13.*frontend npm dependencies/);
  const root = await fixture();
  const run: typeof runCheck = (_cwd, label) => {
    if (label.startsWith("transcription")) throw new Error("export failed");
    return Promise.resolve("");
  };
  await assert.rejects(checkContracts(root, join(root, "cache"), run), /export failed[\s\S]*generate:transcription-contract/);
});
