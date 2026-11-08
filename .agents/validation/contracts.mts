import { access, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { backendPython } from './backend.mts';
import { runCheck } from './shared.mts';

export async function checkContracts(root: string, cache: string, run: typeof runCheck = runCheck): Promise<void> {
  await mkdir(cache, { recursive: true });
  const python = backendPython(root);
  const frontend = join(root, 'frontend');
  try {
    await access(python);
    await access(join(frontend, 'node_modules/@hey-api/openapi-ts'));
  } catch {
    throw new Error('Generated-contract freshness requires backend/.venv Python 3.13 with backend dependencies and frontend npm dependencies. See docs/development.md.');
  }
  await run(root, 'Backend Python 3.13 prerequisite', ['-c', 'import sys; sys.exit("Python 3.13 required") if sys.version_info[:2] != (3, 13) else None'], join(cache, 'python.log'), 30_000, python);
  for (const capability of ['conversation', 'transcription', 'image-generation']) {
    try {
      await run(frontend, `${capability} contract freshness`, [join(frontend, `scripts/${capability}-contract.mjs`), '--check'], join(cache, `${capability}.log`), 120_000, process.execPath, undefined, { ...process.env, PYTHON: python });
    } catch (error: unknown) {
      throw new Error(`${error instanceof Error ? error.message : String(error)}\nCheck setup in docs/development.md; regenerate with npm run generate:${capability}-contract in frontend.`, { cause: error });
    }
  }
}
