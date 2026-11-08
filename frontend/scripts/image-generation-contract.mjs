import { generateContract } from './contract-generator.mjs';

await generateContract({
  name: 'image-generation',
  exportFlag: '--image-generation',
  directory: ['projects', 'image-generation', 'src', 'generated'],
  formatOutput: true,
  zodRequests: true,
});
