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

function mismatchDetails(committed, generated) {
  if (committed === null) return 'The checked-in file is missing.';

  const checkedIn = committed.toString('utf8');
  const produced = generated.toString('utf8');
  if (checkedIn.replaceAll('\r\n', '\n') === produced.replaceAll('\r\n', '\n')) {
    return 'Only line endings differ (CRLF versus LF).';
  }

  const checkedInLines = checkedIn.split(/\r?\n/);
  const producedLines = produced.split(/\r?\n/);
  let line = 0;
  while (line < Math.max(checkedInLines.length, producedLines.length)
    && checkedInLines[line] === producedLines[line]) line++;

  const show = (value) => value === undefined ? '<end of file>' : JSON.stringify(value.slice(0, 240));
  return `First difference at line ${line + 1}:\n  checked-in: ${show(checkedInLines[line])}\n  generated:  ${show(producedLines[line])}`;
}

if (process.argv.length > 3 || (process.argv[2] && !check)) {
  throw new Error('Usage: node scripts/conversation-contract.mjs [--check]');
}

const temporary = await mkdtemp(join(tmpdir(), 'ai-service-contract-'));
try {
  const document = execFileSync(process.env.PYTHON ?? 'python', ['-m', 'scripts.export_openapi'], {
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
        throw new Error(`${destination} is stale. ${mismatchDetails(committed, generated)}\nRun npm run generate:conversation-contract.`);
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
