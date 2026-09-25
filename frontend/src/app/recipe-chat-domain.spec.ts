import { describe, expect, it } from 'vitest';
import { ConversationNetworkError, type ApiArtifact } from './conversation-api';
import { presentRecipeArtifact } from './recipe-chat-domain';

const artifact: ApiArtifact = {
  artifact_id: 'proposal-1', type: 'recipe.proposal', created_at: '2026-09-25T12:00:00Z',
  order: 1, turn_id: 'turn-1',
  payload: { name: 'Neue Variante', recipe: {
    servings: 2, preptime: null, kcal: 100, carbs: 12, protein: 8, fat: 3,
    ingredients: [{ index: 1, amount: 50, foodstuff: {
      id: 1, name: 'Hafer', brand: null, unit: 'G', unitVerbose: 'g',
      kcal: 370, carbs: 60, protein: 13, fat: 7,
    } }],
    steps: [{ index: 1, description: 'Mischen.' }],
  } },
};

describe('recipe artifact mapping', () => {
  it('preserves recipe presentation and backend identity', () => {
    expect(presentRecipeArtifact(artifact)).toEqual({
      kind: 'artifact', id: 'proposal-1', type: 'recipe-proposal', headline: 'Neue Variante',
      payload: {
        servings: 2, preptime: null, kcal: 100, carbs: 12, protein: 8, fat: 3,
        ingredients: [{ index: 1, amount: 50, foodstuff: {
          id: 1, name: 'Hafer', brand: null, unit: 'G', unitVerbose: 'g',
          kcal: 370, carbs: 60, protein: 13, fat: 7,
        } }],
        steps: [{ index: 1, description: 'Mischen.' }],
      },
    });
  });

  it('omits unsupported types and rejects malformed recognized payloads', () => {
    expect(presentRecipeArtifact({ ...artifact, type: 'other.result', payload: null })).toBeNull();
    for (const payload of [null, 'invalid', [], { name: 'Broken' }]) {
      expect(() => presentRecipeArtifact({ ...artifact, payload })).toThrow(ConversationNetworkError);
    }
  });
});
