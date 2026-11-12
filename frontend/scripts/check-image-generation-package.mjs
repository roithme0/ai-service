import { mkdtemp, mkdir, readdir, symlink, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';

const temp = await mkdtemp(join(tmpdir(), 'image-generation-consumer-'));
const run = (command, args) => {
  const result = spawnSync(command, args, { cwd: temp, stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`${command} failed`);
};
const target = join(temp, 'node_modules', '@roithme0', 'image-generation');
await mkdir(target, { recursive: true });
run(process.execPath, [
  join(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js'),
  'pack',
  resolve('dist/image-generation'),
  '--pack-destination',
  temp,
  '--cache',
  join(temp, 'npm-cache'),
]);
const archive = (await readdir(temp)).find((name) => name.endsWith('.tgz'));
if (!archive) throw new Error('Package archive missing');
run('tar', ['-xzf', join(temp, archive), '-C', target, '--strip-components=1']);
for (const dependency of ['zod', 'tslib'])
  await symlink(
    resolve('node_modules', dependency),
    join(temp, 'node_modules', dependency),
    'junction',
  );
await writeFile(join(temp, 'package.json'), '{"type":"module"}');
await writeFile(
  join(temp, 'consumer.ts'),
  `import { ImageGenerationController, HttpImageGenerationTransport, type ImageGenerationState } from '@roithme0/image-generation/controller';
const transport = new HttpImageGenerationTransport('/api/v1', 'issuer:subject', fetch);
const controller = new ImageGenerationController(transport, (state: Readonly<ImageGenerationState>) => { void state; });
async function use(): Promise<void> { await controller.submit('test'); await controller.recoverSubmission(); await controller.readStatus(); controller.reconnect(); await controller.loadContent(); controller.dispose(); }
void use;`,
);
run(process.execPath, [
  resolve('node_modules/typescript/bin/tsc'),
  '--ignoreConfig',
  '--strict',
  '--noEmit',
  '--target',
  'ES2022',
  '--module',
  'NodeNext',
  '--moduleResolution',
  'NodeNext',
  join(temp, 'consumer.ts'),
]);
await writeFile(
  join(temp, 'consumer.mjs'),
  `import * as root from '@roithme0/image-generation';
import { ImageGenerationController, HttpImageGenerationTransport } from '@roithme0/image-generation/controller';
if (Object.keys(root).length) throw Error('Root entrypoint must be empty');

const id = '11111111-1111-4111-8111-111111111111';
const running = { generation_id:id, status:'running', created_at:'2026-01-01T00:00:00Z', completed_at:null, configured_model:'gpt-image-2', provider_model:null, estimated_cost_usd:null };
const completed = { ...running, status:'completed', completed_at:'2026-01-01T00:00:01Z', content:{url:'/ignored',media_type:'image/png',size_bytes:1} };
let posts = 0; let streams = 0; const keys = [];
const fake = async (url, init) => {
 if (init.headers['X-Application-User'] !== 'issuer:subject') throw Error('owner');
 if (init.method === 'POST') { keys.push(init.headers['Idempotency-Key']); posts++; return posts === 1 ? new Response('', {status:503}) : Response.json(running, {status:202}); }
 if (url.endsWith('/events')) { streams++; return new Response(streams === 1 ? '' : 'data: '+JSON.stringify({kind:'snapshot',snapshot:completed})+'\\n\\n', {headers:{'Content-Type':'text/event-stream'}}); }
 if (url.endsWith('/content')) return new Response(new Uint8Array([1]), {headers:{'Content-Type':'image/png'}});
 return Response.json(running);
};
const controller = new ImageGenerationController(new HttpImageGenerationTransport('/api/v1','issuer:subject',fake), () => {});
await controller.submit('test'); if (controller.state.admission !== 'uncertain') throw Error('uncertain');
await controller.recoverSubmission(); await new Promise(resolve => setTimeout(resolve, 0));
if (keys[0] !== keys[1] || controller.state.observation !== 'lost') throw Error('recovery');
await controller.readStatus(); controller.reconnect(); await new Promise(resolve => setTimeout(resolve, 0));
if (controller.state.snapshot.status !== 'completed' || (await controller.loadContent()).blob.size !== 1 || posts !== 2) throw Error('flow'); controller.dispose();`,
);
run(process.execPath, [join(temp, 'consumer.mjs')]);
// Resolve Angular only for the UI consumer, after the controller-only check.
await mkdir(join(temp, 'node_modules', '@angular'), { recursive: true });
for (const dependency of [
  'core',
  'compiler',
  'common',
  'forms',
  'platform-browser',
  'cdk',
  'material',
])
  await symlink(
    resolve('node_modules', '@angular', dependency),
    join(temp, 'node_modules', '@angular', dependency),
    'junction',
  );
await symlink(resolve('node_modules', 'rxjs'), join(temp, 'node_modules', 'rxjs'), 'junction');
await writeFile(
  join(temp, 'ui-consumer.ts'),
  `import { ImageGenerationUiComponent, type ImageGenerationActions, type ImageGenerationHandoff, type ImageGenerationPrimaryAction } from '@roithme0/image-generation/ui';
const action: ImageGenerationPrimaryAction = { label: 'Use image', run: async (payload: ImageGenerationHandoff): Promise<void> => { void payload.blob; } };
const use = (component: ImageGenerationUiComponent, actions: ImageGenerationActions): void => { void component; void actions; void action; }; void use;`,
);
run(process.execPath, [
  resolve('node_modules/typescript/bin/tsc'),
  '--ignoreConfig',
  '--strict',
  '--noEmit',
  '--target',
  'ES2022',
  '--module',
  'NodeNext',
  '--moduleResolution',
  'NodeNext',
  join(temp, 'ui-consumer.ts'),
]);
await writeFile(
  join(temp, 'ui-consumer.mjs'),
  `import '@angular/compiler'; import { ImageGenerationUiComponent } from '@roithme0/image-generation/ui'; if (!ImageGenerationUiComponent) throw Error('UI missing');`,
);
run(process.execPath, [join(temp, 'ui-consumer.mjs')]);
console.log(
  'Packed controller and UI entrypoints, empty root, controller flow and strict declarations verified.',
);
