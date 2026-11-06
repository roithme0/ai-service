import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createClient } from '@hey-api/openapi-ts';
import { format, resolveConfig } from 'prettier';
import { sameContract } from './contract-comparison.mjs';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backend = resolve(frontend, '..', 'backend');
const files = ['openapi.json', 'index.ts', 'types.gen.ts', 'zod.gen.ts'];

function mismatchDetails(committed, generated) {
  if (committed === null) return 'The checked-in file is missing.';
  const checkedInLines = committed.toString('utf8').split(/\r?\n/);
  const producedLines = generated.toString('utf8').split(/\r?\n/);
  let line = 0;
  while (
    line < Math.max(checkedInLines.length, producedLines.length) &&
    checkedInLines[line] === producedLines[line]
  )
    line++;
  const show = (value) =>
    value === undefined ? '<end of file>' : JSON.stringify(value.slice(0, 240));
  return `First difference at line ${line + 1}:\n  checked-in: ${show(checkedInLines[line])}\n  generated:  ${show(producedLines[line])}`;
}

export async function generateContract({ name, exportFlag, directory, formatOutput, zodRequests }) {
  const check = process.argv[2] === '--check';
  if (process.argv.length > 3 || (process.argv[2] && !check)) {
    throw new Error(`Usage: node scripts/${name}-contract.mjs [--check]`);
  }
  const temporary = await mkdtemp(join(tmpdir(), 'ai-service-contract-'));
  try {
    const document = execFileSync(
      process.env.PYTHON ?? 'python',
      ['-m', 'scripts.export_openapi', exportFlag],
      {
        cwd: backend,
        encoding: 'utf8',
      },
    );
    const input = join(temporary, 'openapi.json');
    const output = join(temporary, 'generated');
    await writeFile(input, document);
    await createClient({
      input,
      output,
      plugins: ['@hey-api/typescript', { name: 'zod', requests: zodRequests }],
    });
    for (const file of files) {
      const destination = join(frontend, ...directory, file);
      const source = await readFile(file === 'openapi.json' ? input : join(output, file), 'utf8');
      const generated = Buffer.from(
        formatOutput
          ? await format(source, { ...(await resolveConfig(destination)), filepath: destination })
          : source,
      );
      if (check) {
        const committed = await readFile(destination).catch(() => null);
        if (!committed || !sameContract(committed, generated)) {
          throw new Error(
            `${destination} is stale. ${mismatchDetails(committed, generated)}\nRun npm run generate:${name}-contract.`,
          );
        }
      } else {
        await mkdir(dirname(destination), { recursive: true });
        await writeFile(destination, generated);
      }
    }
    const title = name[0].toUpperCase() + name.slice(1);
    process.stdout.write(
      check ? `${title} contract is current.\n` : `${title} contract generated.\n`,
    );
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}
