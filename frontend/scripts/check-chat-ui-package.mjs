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
const conversation = await import(pathToFileURL(resolve(packageRoot, manifest.exports['./conversation'].default)).href);
assert.deepEqual(conversation.AgentConfiguration, { Demo: 'demo', Kochwiki: 'kochwiki' });
const requests = [];
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  requests.push({ url, options });
  return Response.json({ session_id: 'built-session', expires_at: '2026-09-26T12:00:00Z' });
};
try {
  const controller = new conversation.ConversationController(
    new conversation.HttpConversationTransport('/ai/api/v1/', conversation.AgentConfiguration.Demo),
    () => {},
  );
  await controller.start();
  await controller.performAction('new-session');
  assert.equal(controller.state.composerDisabled, false);
  assert.equal(requests.length, 2);
  for (const request of requests) {
    assert.equal(request.url, '/ai/api/v1/agents/demo/sessions');
    assert.deepEqual(JSON.parse(request.options.body), { input: {} });
  }
} finally {
  globalThis.fetch = originalFetch;
}

const consumer = await mkdtemp(resolve(tmpdir(), 'chat-ui-consumer-'));
await mkdir(resolve(consumer, 'node_modules/@roithme0'), { recursive: true });
await symlink(packageRoot, resolve(consumer, 'node_modules/@roithme0/chat-ui'), 'junction');
for (const dependency of ['@angular', 'rxjs', 'tslib']) {
  await symlink(resolve(frontend, 'node_modules', dependency), resolve(consumer, 'node_modules', dependency), 'junction');
}
const source = resolve(consumer, 'consumer.mts');
await writeFile(source, `
import { ChatUiComponent, artifactRenderer, type ChatSubmission, type ChatContent } from '@roithme0/chat-ui/ui';
import { AgentConfiguration, ConversationController, HttpConversationTransport, presentJsonArtifact,
  ConversationApiError, ConversationNetworkError,
  type AgentConfiguration as Configuration, type ArtifactMapper, type ConversationViewState,
  type ConversationTransport, type ApiArtifact, type ApiMessage, type ApiUserMessage,
  type ApiAssistantMessage, type SessionCreation, type SessionSnapshot, type TurnResult
} from '@roithme0/chat-ui/conversation';
import * as Root from '@roithme0/chat-ui';
const emptyRoot: keyof typeof Root extends never ? true : false = true;
const config: Configuration = AgentConfiguration.Demo;
const publish = (state: ConversationViewState): void => { const content: readonly ChatContent[] = state.content; };
const transport: ConversationTransport = new HttpConversationTransport('/api/v1', config);
const controller = new ConversationController(transport, publish);
const mapper: ArtifactMapper = (artifact: ApiArtifact) => presentJsonArtifact(artifact);
new ConversationController(new HttpConversationTransport('/ai/api/v1/', AgentConfiguration.Kochwiki, { source: {} }), publish, mapper);
// @ts-expect-error Arbitrary agent keys are not public configuration.
new HttpConversationTransport('/api/v1', 'arbitrary');
// @ts-expect-error Root compatibility exports must be absent.
Root.ChatUiComponent;
// @ts-expect-error Internal parsing is not public API.
import { parseSessionSnapshot } from '@roithme0/chat-ui/conversation';
// @ts-expect-error Private implementation subpaths must remain inaccessible.
import { ConversationController as PrivateController } from '@roithme0/chat-ui/conversation/src/conversation-controller';
`);
const program = ts.createProgram([source], {
  strict: true, noEmit: true, target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.NodeNext, moduleResolution: ts.ModuleResolutionKind.NodeNext,
  experimentalDecorators: true, skipLibCheck: false,
});
const diagnostics = ts.getPreEmitDiagnostics(program);
if (diagnostics.length) {
  throw new Error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {
    getCanonicalFileName: (name) => name, getCurrentDirectory: () => consumer, getNewLine: () => '\n',
  }));
}
console.log('Built package exports, runtime, configuration and strict consumer declarations passed.');
