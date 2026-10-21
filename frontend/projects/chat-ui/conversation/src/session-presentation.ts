import type { ChatArtifact, ChatContent, ChatTurn, ChatTurnStatus } from '@roithme0/chat-ui/ui';
import type {
  PresentedSession,
  PresentedTurn,
  PresentationPart,
  PublishedArtifactArtifactPayload,
  UserPrompt,
} from '../generated/types.gen';

export type SessionArtifactMapper = (
  artifact: PublishedArtifactArtifactPayload,
) => ChatArtifact | null;

export function presentSessionArtifact(artifact: PublishedArtifactArtifactPayload): ChatArtifact {
  return {
    kind: 'artifact',
    id: artifact.artifact_id,
    type: artifact.type,
    headline: artifact.payload.title,
    payload: artifact.payload.payload,
    ...(artifact.payload.subtitle === null || artifact.payload.subtitle === undefined
      ? {}
      : { subtitle: artifact.payload.subtitle }),
    ...(artifact.payload.metadata === null || artifact.payload.metadata === undefined
      ? {}
      : { metadata: artifact.payload.metadata }),
  };
}

export function presentSession(
  snapshot: PresentedSession,
  observationLost = false,
  mapArtifact: SessionArtifactMapper = presentSessionArtifact,
): readonly ChatTurn[] {
  const groups = presentHistory(snapshot, observationLost, mapArtifact);
  const answerIds = findAnswerIds(groups);
  const lastGroupIndices = findLastGroupIndices(groups);

  return groups.map((group, index) => {
    if (group.runKey === null) return group;
    return finishGroup(
      group,
      answerIds.get(group.runKey),
      lastGroupIndices.get(group.runKey) === index,
    );
  });
}

function presentHistory(
  snapshot: PresentedSession,
  observationLost: boolean,
  mapArtifact: SessionArtifactMapper,
): ChatTurn[] {
  const groups: ChatTurn[] = [];
  const runOrdinals = new Map<string, number>();
  const groupCounts = new Map<number, number>();
  let nextRun = 0;
  let prompt = 0;
  const scope = `${JSON.stringify(snapshot.session_id)}:`;

  for (const item of snapshot.history) {
    if (item.part_kind === 'user-prompt') {
      groups.push(presentPrompt(item, `${scope}prompt-${prompt++}`));
      continue;
    }
    const runId = item.lifecycle.run_id;
    let ordinal = runId === null ? undefined : runOrdinals.get(runId);
    if (ordinal === undefined) {
      ordinal = nextRun++;
      if (runId !== null) runOrdinals.set(runId, ordinal);
    }
    const group = groupCounts.get(ordinal) ?? 0;
    groupCounts.set(ordinal, group + 1);
    const runKey = `${scope}run-${ordinal}`;
    groups.push(presentRunGroup(item, runKey, group, observationLost, mapArtifact));
  }

  return groups;
}

function presentPrompt(prompt: UserPrompt, id: string): ChatTurn {
  const fragments = typeof prompt.content === 'string' ? [prompt.content] : prompt.content;
  return {
    runKey: null,
    status: 'prompt',
    content: fragments.map((text, index) => ({
      kind: 'text',
      id: `${id}-${index}`,
      text,
      role: 'user',
      isFinal: false,
    })),
  };
}

function presentRunGroup(
  turn: PresentedTurn,
  runKey: string,
  groupOrdinal: number,
  observationLost: boolean,
  mapArtifact: SessionArtifactMapper,
): ChatTurn {
  const id = `${runKey}-group-${groupOrdinal}`;
  return {
    runKey,
    status: presentRunStatus(turn.lifecycle.status, observationLost),
    content: turn.parts.flatMap((part, index) => presentPart(part, `${id}-${index}`, mapArtifact)),
  };
}

function presentRunStatus(
  status: PresentedTurn['lifecycle']['status'],
  observationLost: boolean,
): ChatTurnStatus {
  if (status !== 'running') return status;
  return observationLost ? 'unknown' : 'active';
}

function findAnswerIds(groups: readonly ChatTurn[]): ReadonlyMap<string, string> {
  const finalAnswers = new Map<string, string>();
  const unphasedAnswers = new Map<string, string>();
  for (const group of groups) {
    const key = group.runKey;
    if (key === null) continue;
    for (const item of group.content) {
      if (item.kind !== 'text') continue;
      if (item.isFinal) {
        if (!finalAnswers.has(key)) finalAnswers.set(key, item.id);
      } else unphasedAnswers.set(key, item.id);
    }
  }

  return new Map([...unphasedAnswers, ...finalAnswers]);
}

function findLastGroupIndices(groups: readonly ChatTurn[]): ReadonlyMap<string, number> {
  const lastGroups = new Map<string, number>();
  groups.forEach((group, index) => {
    if (group.runKey !== null) lastGroups.set(group.runKey, index);
  });
  return lastGroups;
}

function finishGroup(
  group: ChatTurn,
  answerId: string | undefined,
  isLastGroup: boolean,
): ChatTurn {
  if (group.status === 'prompt') return group;

  const content = group.content.map((item): ChatContent => {
    if (item.kind === 'text' && item.id === answerId) return { ...item, isFinal: true };
    return item;
  });

  if (isLastGroup && (group.status === 'failed' || group.status === 'cancelled')) {
    content.push({
      kind: 'failure',
      id: `${group.runKey}-failure`,
      text:
        group.status === 'cancelled'
          ? 'Die Antwort wurde abgebrochen.'
          : 'Die Antwort konnte nicht erstellt werden.',
    });
  }

  return { ...group, content };
}

function presentPart(
  part: PresentationPart,
  id: string,
  mapArtifact: SessionArtifactMapper,
): ChatContent[] {
  switch (part.part_kind) {
    case 'text':
      return part.phase === 'commentary'
        ? [{ kind: 'intermediate', id, text: part.content }]
        : [
            {
              kind: 'text',
              id,
              role: 'assistant',
              text: part.content,
              isFinal: part.phase === 'final_answer',
            },
          ];
    case 'tool-call':
    case 'builtin-tool-call':
      return [
        {
          kind: 'tool',
          id,
          name: part.tool_name,
          status:
            part.status === 'success'
              ? 'completed'
              : part.status === 'denied'
                ? 'not_executed'
                : part.status === 'interrupted'
                  ? 'outcome_unknown'
                  : part.status,
        },
      ];
    case 'artifact': {
      const artifact = mapArtifact(part.artifact);
      return artifact === null ? [] : [artifact];
    }
  }
}
