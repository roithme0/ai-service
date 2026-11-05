import type { AudioRecording } from '@roithme0/chat-ui/recording';
import {
  zHttpErrorResponse,
  zTranscriptionErrorResponse,
  zTranscriptionResponse,
} from './generated/zod.gen';
import type { HttpErrorResponse, TranscriptionErrorResponse } from './generated/types.gen';

export type TranscriptionErrorKind =
  TranscriptionErrorResponse['kind'] | HttpErrorResponse['kind'] | 'network' | 'invalid_response';

export class TranscriptionError extends Error {
  constructor(
    readonly kind: TranscriptionErrorKind,
    readonly status?: number,
  ) {
    super(`Transcription failed: ${kind}`);
  }
}

export class HttpTranscriber {
  private readonly url: string;
  constructor(apiBaseUrl: string) {
    this.url = `${apiBaseUrl.replace(/\/+$/, '')}/transcriptions`;
  }

  async transcribe(recording: AudioRecording, signal: AbortSignal): Promise<string> {
    let response: Response;
    try {
      response = await fetch(this.url, {
        method: 'POST',
        headers: { 'Content-Type': recording.mimeType },
        body: recording.blob,
        signal,
      });
    } catch {
      signal.throwIfAborted();
      throw new TranscriptionError('network');
    }
    let payload: unknown;
    try {
      payload = await response.json();
      signal.throwIfAborted();
    } catch {
      signal.throwIfAborted();
      throw new TranscriptionError('invalid_response', response.status);
    }
    if (!response.ok) {
      const parsed = zTranscriptionErrorResponse.safeParse(payload);
      const generic = zHttpErrorResponse.safeParse(payload);
      if (parsed.success) throw new TranscriptionError(parsed.data.kind, response.status);
      if (generic.success) throw new TranscriptionError(generic.data.kind, response.status);
      throw new TranscriptionError('invalid_response', response.status);
    }
    const parsed = zTranscriptionResponse.safeParse(payload);
    if (response.status !== 200 || !parsed.success)
      throw new TranscriptionError('invalid_response', response.status);
    return parsed.data.text;
  }
}
