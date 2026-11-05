import { generateContract } from './contract-generator.mjs';

await generateContract({
  name: 'transcription',
  exportFlag: '--transcription',
  directory: ['projects', 'chat-ui', 'transcription', 'src', 'generated'],
  formatOutput: true,
  zodRequests: false,
});
