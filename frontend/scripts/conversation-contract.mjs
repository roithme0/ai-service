import { generateContract } from './contract-generator.mjs';

await generateContract({
  name: 'conversation',
  exportFlag: '--native',
  directory: ['projects', 'chat-ui', 'conversation', 'generated'],
  formatOutput: false,
  zodRequests: true,
});
