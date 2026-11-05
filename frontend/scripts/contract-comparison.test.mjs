import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sameContract } from './contract-comparison.mjs';

test('contract comparison ignores checkout line endings only', () => {
  assert.equal(sameContract(Buffer.from('a\r\nb\r\n'), Buffer.from('a\nb\n')), true);
  assert.equal(sameContract(Buffer.from('a\nb\n'), Buffer.from('a\nc\n')), false);
  assert.equal(sameContract(Buffer.from('a\n'), Buffer.from('a')), false);
});

test('transcription OpenAPI declares each supported binary media type and route responses', async () => {
  const { readFile } = await import('node:fs/promises');
  const schema = JSON.parse(
    await readFile(
      new URL('../projects/chat-ui/transcription/src/generated/openapi.json', import.meta.url),
      'utf8',
    ),
  );
  assert.deepEqual(Object.keys(schema.paths), ['/api/v1/transcriptions']);
  const operation = schema.paths['/api/v1/transcriptions'].post;
  assert.equal(operation.requestBody.required, true);
  assert.deepEqual(
    Object.keys(operation.requestBody.content).sort(),
    [
      'audio/flac',
      'audio/m4a',
      'audio/mp3',
      'audio/mp4',
      'audio/mpeg',
      'audio/mpga',
      'audio/ogg',
      'audio/wav',
      'audio/wave',
      'audio/webm',
      'audio/x-flac',
      'audio/x-m4a',
      'audio/x-wav',
    ].sort(),
  );
  for (const media of Object.values(operation.requestBody.content)) {
    assert.deepEqual(media.schema, { type: 'string', format: 'binary' });
  }
  assert.deepEqual(Object.keys(operation.responses).sort(), [
    '200',
    '413',
    '415',
    '422',
    '500',
    '502',
    '503',
    '504',
  ]);
});

test('generated transcription validators accept valid responses and reject malformed data', async () => {
  const validators = await import('../projects/chat-ui/transcription/src/generated/zod.gen.ts');
  const { zTranscriptionResponse, zTranscriptionErrorResponse, zHttpErrorResponse } = validators;
  assert.equal('zTranscribeApiV1TranscriptionsPostBody' in validators, false);
  for (const text of ['', '  multilingual ??  '])
    assert.equal(zTranscriptionResponse.safeParse({ text }).success, true);
  for (const value of [{}, { text: 42 }, { text: null }])
    assert.equal(zTranscriptionResponse.safeParse(value).success, false);
  for (const kind of [
    'audio_too_large',
    'unsupported_audio',
    'invalid_audio',
    'transcription_unavailable',
    'transcription_timeout',
    'transcription_failed',
  ]) {
    assert.equal(zTranscriptionErrorResponse.safeParse({ kind, detail: 'safe' }).success, true);
  }
  assert.equal(
    zTranscriptionErrorResponse.safeParse({ kind: 'unknown', detail: 'safe' }).success,
    false,
  );
  assert.equal(
    zTranscriptionErrorResponse.safeParse({ kind: 'invalid_audio', detail: '' }).success,
    false,
  );
  assert.equal(
    zHttpErrorResponse.safeParse({ kind: 'internal_error', detail: 'safe' }).success,
    true,
  );
});

test('generated transcription request accepts a Blob and rejects JSON text', async () => {
  const ts = await import('typescript');
  const filename = new URL(
    '../projects/chat-ui/transcription/src/generated/__typecheck__.ts',
    import.meta.url,
  ).pathname.replace(/^\/(\w:)/, '$1');
  const source = `import type { TranscribeApiV1TranscriptionsPostData } from './types.gen';\nconst valid: TranscribeApiV1TranscriptionsPostData = { body: new Blob(), url: '/api/v1/transcriptions' };\nconst file: TranscribeApiV1TranscriptionsPostData = { body: new File([], 'audio.ogg'), url: '/api/v1/transcriptions' };\n// @ts-expect-error JSON strings are not raw audio blobs\nconst invalid: TranscribeApiV1TranscriptionsPostData = { body: 'audio', url: '/api/v1/transcriptions' };\nvoid valid; void file; void invalid;`;
  const options = {
    noEmit: true,
    strict: true,
    skipLibCheck: true,
    module: ts.ModuleKind.NodeNext,
    moduleResolution: ts.ModuleResolutionKind.NodeNext,
    target: ts.ScriptTarget.ES2022,
  };
  const host = ts.createCompilerHost(options);
  const originalRead = host.readFile.bind(host);
  const originalExists = host.fileExists.bind(host);
  host.readFile = (path) => (path === filename ? source : originalRead(path));
  host.fileExists = (path) => path === filename || originalExists(path);
  const program = ts.createProgram([filename], options, host);
  const diagnostics = ts.getPreEmitDiagnostics(program);
  assert.deepEqual(
    diagnostics.map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')),
    [],
  );
});
