import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createClient } from '@hey-api/openapi-ts';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backend = resolve(frontend, '..', 'backend');
const contract = join(frontend, 'projects', 'chat-ui', 'conversation', 'generated');
const files = ['openapi.json', 'index.ts', 'types.gen.ts', 'zod.gen.ts'];
const check = process.argv[2] === '--check';

if (process.argv.length > 3 || (process.argv[2] && !check)) {
  throw new Error('Usage: node scripts/conversation-contract.mjs [--check]');
}

const temporary = await mkdtemp(join(tmpdir(), 'ai-service-contract-'));
try {
  const document = execFileSync(process.env.PYTHON ?? 'python', ['-m', 'app.export_openapi'], {
    cwd: backend,
    encoding: 'utf8',
  });
  const input = join(temporary, 'openapi.json');
  const output = join(temporary, 'generated');
  await writeFile(input, document);
  await createClient({ input, output, plugins: ['@hey-api/typescript', 'zod'] });

  for (const name of files) {
    const generated = await readFile(name === 'openapi.json' ? input : join(output, name));
    const destination = join(contract, name);
    if (check) {
      const committed = await readFile(destination).catch(() => null);
      if (!committed?.equals(generated)) {
        throw new Error(`${destination} is stale. Run npm run generate:conversation-contract.`);
      }
    } else {
      await mkdir(contract, { recursive: true });
      await writeFile(destination, generated);
    }
  }
  process.stdout.write(check ? 'Conversation contract is current.\n' : 'Conversation contract generated.\n');
} finally {
  await rm(temporary, { recursive: true, force: true });
}
