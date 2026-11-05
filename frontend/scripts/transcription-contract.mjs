import { generateContract } from './contract-generator.mjs';

await generateContract({
  name: 'transcription',
  exportFlag: '--transcription',
  directory: ['contracts', 'transcription', 'generated'],
  formatOutput: true,
  zodRequests: false,
});
