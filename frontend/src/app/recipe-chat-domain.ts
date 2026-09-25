import type { ChatArtifact, JsonValue } from '@roithme0/chat-ui';
import { ConversationNetworkError, type ApiArtifact } from './conversation-api';

export interface FoodstuffSummary {
  readonly id: number;
  readonly name: string;
  readonly brand: string | null;
  readonly unit: 'G' | 'ML' | 'PIECE';
  readonly unitVerbose: string;
  readonly kcal: number | null;
  readonly carbs: number | null;
  readonly protein: number | null;
  readonly fat: number | null;
}

export interface RecipePresentation {
  readonly servings: number;
  readonly preptime: number | null;
  readonly kcal: number | null;
  readonly carbs: number | null;
  readonly protein: number | null;
  readonly fat: number | null;
  readonly ingredients: ReadonlyArray<{
    readonly index: number;
    readonly amount: number;
    readonly foodstuff: FoodstuffSummary;
  }>;
  readonly steps: ReadonlyArray<{ readonly index: number; readonly description: string }>;
}

export interface RecipeProposal {
  readonly artifact_id: string;
  readonly turn_id: string;
  readonly name: string;
  readonly recipe: RecipePresentation;
}

export interface RecipeSessionRequest {
  readonly source: {
    readonly external_reference: string;
    readonly recipe: {
      readonly name: string;
      readonly servings: number;
      readonly preparation_time: number | null;
      readonly origin_name: string | null;
      readonly origin_url: string | null;
      readonly ingredients: ReadonlyArray<{
        readonly index: number;
        readonly amount: number;
        readonly foodstuff_reference: number;
      }>;
      readonly steps: ReadonlyArray<{ readonly index: number; readonly description: string }>;
    };
  };
  readonly foodstuffs: ReadonlyArray<{
    readonly external_reference: number;
    readonly name: string;
    readonly brand: string | null;
    readonly unit: 'G' | 'ML' | 'PIECE';
    readonly unit_verbose: string;
    readonly kcal: number | null;
    readonly carbs: number | null;
    readonly protein: number | null;
    readonly fat: number | null;
  }>;
}

function parseRecipeArtifact(artifact: ApiArtifact): RecipeProposal | null {
  if (artifact.type !== 'recipe.proposal') return null;
  if (!isRecord(artifact.payload)) throw invalidResponse();
  const name = readString(artifact.payload, 'name');
  if (name === null) throw invalidResponse();
  return {
    artifact_id: artifact.artifact_id,
    turn_id: artifact.turn_id,
    name,
    recipe: parsePresentation(artifact.payload['recipe']),
  };
}

function parsePresentation(value: unknown): RecipePresentation {
  if (!isRecord(value) || !Array.isArray(value['ingredients']) || !Array.isArray(value['steps'])) {
    throw invalidResponse();
  }
  return {
    servings: readNumber(value, 'servings'),
    preptime: readNullableNumber(value, 'preptime'),
    kcal: readNullableNumber(value, 'kcal'),
    carbs: readNullableNumber(value, 'carbs'),
    protein: readNullableNumber(value, 'protein'),
    fat: readNullableNumber(value, 'fat'),
    ingredients: value['ingredients'].map((ingredient) => {
      if (!isRecord(ingredient)) throw invalidResponse();
      return {
        index: readNumber(ingredient, 'index'),
        amount: readNumber(ingredient, 'amount'),
        foodstuff: parseFoodstuff(ingredient['foodstuff']),
      };
    }),
    steps: value['steps'].map((step) => {
      if (!isRecord(step)) throw invalidResponse();
      const description = readString(step, 'description');
      if (description === null) throw invalidResponse();
      return { index: readNumber(step, 'index'), description };
    }),
  };
}

function parseFoodstuff(value: unknown): FoodstuffSummary {
  if (!isRecord(value)) throw invalidResponse();
  const name = readString(value, 'name');
  const brand = readNullableString(value, 'brand');
  const unit = readString(value, 'unit');
  const unitVerbose = readString(value, 'unitVerbose');
  if (name === null || unitVerbose === null || (unit !== 'G' && unit !== 'ML' && unit !== 'PIECE')) {
    throw invalidResponse();
  }
  return {
    id: readNumber(value, 'id'), name, brand, unit, unitVerbose,
    kcal: readNullableNumber(value, 'kcal'), carbs: readNullableNumber(value, 'carbs'),
    protein: readNullableNumber(value, 'protein'), fat: readNullableNumber(value, 'fat'),
  };
}

function readNumber(value: Record<string, unknown>, key: string): number {
  const field = value[key];
  if (typeof field !== 'number' || !Number.isFinite(field)) throw invalidResponse();
  return field;
}

function readNullableNumber(value: Record<string, unknown>, key: string): number | null {
  return value[key] === null ? null : readNumber(value, key);
}

function readString(value: unknown, key: string): string | null {
  if (!isRecord(value)) return null;
  const field = value[key];
  return typeof field === 'string' ? field : null;
}

function readNullableString(value: Record<string, unknown>, key: string): string | null {
  const field = value[key];
  if (field === null) return null;
  if (typeof field === 'string') return field;
  throw invalidResponse();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidResponse(): ConversationNetworkError {
  return new ConversationNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
}

export function presentRecipeArtifact(artifact: ApiArtifact): ChatArtifact | null {
  const proposal = parseRecipeArtifact(artifact);
  if (proposal === null) return null;
  return {
    kind: 'artifact', id: proposal.artifact_id, type: 'recipe-proposal', headline: proposal.name,
    payload: {
      servings: proposal.recipe.servings, preptime: proposal.recipe.preptime,
      kcal: proposal.recipe.kcal, carbs: proposal.recipe.carbs, protein: proposal.recipe.protein,
      fat: proposal.recipe.fat,
      ingredients: proposal.recipe.ingredients.map((ingredient) => ({
        index: ingredient.index, amount: ingredient.amount,
        foodstuff: { ...ingredient.foodstuff },
      })),
      steps: proposal.recipe.steps.map((step) => ({ ...step })),
    } satisfies JsonValue,
  };
}

