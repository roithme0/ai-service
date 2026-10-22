import type { ChatArtifact, ChatContent, ChatTurn, ChatTurnStatus } from '@roithme0/chat-ui/ui';
import type {
  PresentedSession,
  PresentedTurn,
  PresentationPart,
  PublishedArtifact,
  UserPrompt,
} from '../generated/types.gen';

export type SessionArtifactMapper = (artifact: PublishedArtifact) => ChatArtifact | null;

export function presentSessionArtifact(artifact: PublishedArtifact): ChatArtifact {
  return {
    kind: 'artifact',
    id: artifact.artifact_id,
    type: artifact.type,
    headline: artifact.content.title,
    payload: artifact.content.payload,
    ...(artifact.content.subtitle === null || artifact.content.subtitle === undefined
      ? {}
      : { subtitle: artifact.content.subtitle }),
    ...(artifact.content.metadata === null || artifact.content.metadata === undefined
      ? {}
      : { metadata: artifact.content.metadata }),
  };
}

export function presentSession(
  snapshot: PresentedSession,
  observationLost = false,
  mapArtifact: SessionArtifactMapper = presentSessionArtifact,
): readonly ChatTurn[] {
  const groups = presentHistory(snapshot, observationLost, mapArtifact);
  const lastGroupIndices = findLastGroupIndices(groups);

  return groups.map((group, index) =>
    group.runKey !== null && lastGroupIndices.get(group.runKey) === index
      ? appendRunFailure(group)
      : group,
  );
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

function findLastGroupIndices(groups: readonly ChatTurn[]): ReadonlyMap<string, number> {
  const lastGroups = new Map<string, number>();
  groups.forEach((group, index) => {
    if (group.runKey !== null) lastGroups.set(group.runKey, index);
  });
  return lastGroups;
}

function appendRunFailure(group: ChatTurn): ChatTurn {
  if (group.status !== 'failed' && group.status !== 'cancelled') return group;
  return {
    ...group,
    content: [
      ...group.content,
      {
        kind: 'failure',
        id: `${group.runKey}-failure`,
        text:
          group.status === 'cancelled'
            ? 'Die Antwort wurde abgebrochen.'
            : 'Die Antwort konnte nicht erstellt werden.',
      },
    ],
  };
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
