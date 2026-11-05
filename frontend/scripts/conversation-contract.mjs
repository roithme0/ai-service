import { generateContract } from './contract-generator.mjs';

await generateContract({
  name: 'conversation',
  exportFlag: '--native',
  directory: ['projects', 'chat-ui', 'conversation', 'src', 'generated'],
  formatOutput: false,
  zodRequests: true,
});
