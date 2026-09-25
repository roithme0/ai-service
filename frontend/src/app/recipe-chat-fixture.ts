import type { RecipeSessionRequest } from './recipe-chat-domain';

export const RECIPE_SESSION_FIXTURE: RecipeSessionRequest = {
  source: {
    external_reference: '3fa85f64-5717-4562-b3fc-2c963f66afa6',
    recipe: {
      name: 'Overnight Oats',
      servings: 2,
      preparation_time: 15,
      origin_name: 'POC',
      origin_url: null,
      ingredients: [{ index: 1, amount: 125.75, foodstuff_reference: 1 }],
      steps: [{ index: 1, description: 'Zutaten vermischen und kalt stellen.' }],
    },
  },
  foodstuffs: [{
    external_reference: 1, name: 'Haferflocken', brand: null, unit: 'G', unit_verbose: 'g',
    kcal: 372, carbs: 59, protein: 13.5, fat: 7,
  }],
};
