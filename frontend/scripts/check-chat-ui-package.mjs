import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageRoot = resolve(frontend, 'dist/chat-ui');
const manifest = JSON.parse(await readFile(resolve(packageRoot, 'package.json'), 'utf8'));
for (const entry of ['.', './ui', './conversation']) {
  assert.ok(manifest.exports[entry]?.types, `Missing declarations for ${entry}`);
  assert.ok(manifest.exports[entry]?.default, `Missing JavaScript for ${entry}`);
}
const root = await import(pathToFileURL(resolve(packageRoot, manifest.exports['.'].default)).href);
assert.deepEqual(Object.keys(root), [], 'Root must export no API');
const conversation = await import(
  pathToFileURL(resolve(packageRoot, manifest.exports['./conversation'].default)).href
);
const requests = [];
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  requests.push({ url, options });
  if (options.method === 'POST') {
    return Response.json(
      { session_id: 'built-session', expires_at: '2026-09-26T12:00:00Z' },
      { status: 201 },
    );
  }
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            `data: ${JSON.stringify({
              kind: 'snapshot',
              snapshot: {
                session_id: 'built-session',
                expires_at: '2026-09-26T12:00:00Z',
                history: [],
              },
            })}\n\n`,
          ),
        );
        options.signal.addEventListener('abort', () => controller.close(), { once: true });
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  );
};
const controller = new conversation.SessionController(
  new conversation.HttpSessionTransport('/ai/api/v1/', 'visual-demo', 'demo:default'),
  () => {},
);
try {
  await controller.start();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(controller.state.composerDisabled, false);
  await controller.performAction('new-session');
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(controller.state.composerDisabled, false);
  assert.equal(requests.length, 4);
  for (const request of requests) {
    if (request.options.method === 'POST') {
      assert.equal(request.url, '/ai/api/v1/agents/visual-demo/sessions');
      assert.deepEqual(JSON.parse(request.options.body), {});
    } else {
      assert.equal(request.url, '/ai/api/v1/agents/visual-demo/sessions/built-session/events');
    }
    assert.equal(request.options.headers['X-Application-User'], 'demo:default');
  }
} finally {
  controller.dispose();
  globalThis.fetch = originalFetch;
}

const consumer = await mkdtemp(resolve(tmpdir(), 'chat-ui-consumer-'));
await mkdir(resolve(consumer, 'node_modules/@roithme0'), { recursive: true });
await symlink(packageRoot, resolve(consumer, 'node_modules/@roithme0/chat-ui'), 'junction');
for (const dependency of ['@angular', 'rxjs', 'tslib']) {
  await symlink(
    resolve(frontend, 'node_modules', dependency),
    resolve(consumer, 'node_modules', dependency),
    'junction',
  );
}
const source = resolve(consumer, 'consumer.mts');
await writeFile(
  source,
  `
import { ChatUiComponent, artifactRenderer, type ChatSubmission, type ChatTurn } from '@roithme0/chat-ui/ui';
import { SessionController, HttpSessionTransport, presentSessionArtifact,
  SessionHttpError, SessionTransportError,
  type SessionArtifactMapper, type SessionViewState, type SessionTransport
} from '@roithme0/chat-ui/conversation';
import * as Root from '@roithme0/chat-ui';
const emptyRoot: keyof typeof Root extends never ? true : false = true;
const publish = (state: SessionViewState): void => { const turns: readonly ChatTurn[] = state.turns; };
const transport: SessionTransport = new HttpSessionTransport('/api/v1', 'visual-demo', 'demo:default');
const controller = new SessionController(transport, publish);
const mapper: SessionArtifactMapper = presentSessionArtifact;
new SessionController(new HttpSessionTransport('/ai/api/v1/', 'kochwiki', 'kochwiki:42'), publish, mapper);
// @ts-expect-error Application identity is required.
new HttpSessionTransport('/api/v1', 'visual-demo');
// @ts-expect-error Root compatibility exports must be absent.
Root.ChatUiComponent;
// @ts-expect-error Internal parsing is not public API.
import { parseSessionSnapshot } from '@roithme0/chat-ui/conversation';
// @ts-expect-error Private implementation subpaths must remain inaccessible.
import { SessionController as PrivateController } from '@roithme0/chat-ui/conversation/src/session-controller';
`,
);
const program = ts.createProgram([source], {
  strict: true,
  noEmit: true,
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.NodeNext,
  moduleResolution: ts.ModuleResolutionKind.NodeNext,
  experimentalDecorators: true,
  skipLibCheck: false,
});
const diagnostics = ts.getPreEmitDiagnostics(program);
if (diagnostics.length) {
  throw new Error(
    ts.formatDiagnosticsWithColorAndContext(diagnostics, {
      getCanonicalFileName: (name) => name,
      getCurrentDirectory: () => consumer,
      getNewLine: () => '\n',
    }),
  );
}
console.log(
  'Built package exports, runtime, configuration and strict consumer declarations passed.',
);
