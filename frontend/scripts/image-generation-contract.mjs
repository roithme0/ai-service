import { generateContract } from './contract-generator.mjs';

await generateContract({
  name: 'image-generation',
  exportFlag: '--image-generation',
  directory: ['projects', 'image-generation', 'controller', 'src', 'generated'],
  formatOutput: true,
  zodRequests: true,
});
