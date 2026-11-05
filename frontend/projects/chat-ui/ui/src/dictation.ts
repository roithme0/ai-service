import type {
  AudioRecording,
  RecordingErrorKind,
  RecordingOutcome,
  RecordingState,
} from '@roithme0/chat-ui/recording';
import type { TranscriptionErrorKind } from '@roithme0/chat-ui/transcription';

export interface DictationRecorder {
  start(): Promise<RecordingOutcome>;
  stop(): void;
  cancel(): void;
  dispose(): void;
}

export type DictationError =
  | { readonly kind: 'recording'; readonly reason: RecordingErrorKind }
  | { readonly kind: 'transcription'; readonly reason: TranscriptionErrorKind };

export interface DictationConfig {
  readonly createRecorder: (publish: (state: RecordingState) => void) => DictationRecorder;
  readonly transcribe: (recording: AudioRecording, signal: AbortSignal) => Promise<string>;
  readonly onError: (error: DictationError) => void;
}
