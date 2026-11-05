export type RecordingState =
  'ready' | 'requesting-access' | 'recording' | 'finalizing' | 'disposed';

export type RecordingStopReason = 'manual' | 'duration-limit';

export type RecordingErrorKind =
  | 'unsupported'
  | 'permission-denied'
  | 'microphone-unavailable'
  | 'capture-interrupted'
  | 'recorder-failed'
  | 'empty-recording'
  | 'busy'
  | 'disposed';

export interface AudioRecording {
  readonly blob: Blob;
  readonly mimeType: string;
  readonly durationMs: number;
  readonly stopReason: RecordingStopReason;
}

export type RecordingOutcome =
  | { readonly kind: 'recorded'; readonly recording: AudioRecording }
  | { readonly kind: 'cancelled' }
  | { readonly kind: 'failed'; readonly error: RecordingErrorKind };
