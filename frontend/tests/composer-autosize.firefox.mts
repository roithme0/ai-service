import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

// Run with node tests/composer-autosize.firefox.mts; FIREFOX_BIN can override the browser path.
const root = new URL('../', import.meta.url);
const styles = await readFile(new URL('projects/chat-ui/ui/lib/chat-ui.component.scss', root), 'utf8');
const textareaStyles = styles.match(/^textarea \{[\s\S]*?^\}/m)?.[0];
if (!textareaStyles) throw new Error('Composer textarea styles were not found.');
const cdkStyles = await readFile(new URL('node_modules/@angular/cdk/text-field-prebuilt.css', root), 'utf8');
const cdkSource = await readFile(new URL('node_modules/@angular/cdk/fesm2022/text-field.mjs', root), 'utf8');
const measurement = cdkSource.match(/  _measureScrollHeight\(\) \{[\s\S]*?\n  \}/)?.[0];
if (!measurement) throw new Error('CDK measurement method was not found.');

const work = await mkdtemp(join(tmpdir(), 'composer-firefox-'));
interface BrowserResult {
  readonly checks: number;
  readonly failures: readonly { readonly width: number; readonly sample: string; readonly length: number; readonly height: number; readonly fullHeight: number }[];
  readonly grew: boolean;
  readonly capped: boolean;
  readonly shrank: boolean;
}
const { promise: result, resolve: resolveResult } = Promise.withResolvers<BrowserResult>();
const server = createServer((request, response) => {
  let body = '';
  request.setEncoding('utf8');
  request.on('data', (chunk) => { body += chunk; });
  request.on('end', () => {
    response.setHeader('Access-Control-Allow-Origin', '*');
    response.end('ok');
    resolveResult(JSON.parse(body));
  });
});
await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
const address = server.address();
if (!address || typeof address === 'string') throw new Error('Test server did not start.');
const html = `<!doctype html><meta charset="utf-8">
<style>
* { box-sizing:border-box; }
body { font:16px monospace; }
.surface { display:flex; flex-direction:column; }
${textareaStyles}
${cdkStyles}
</style>
<div class="surface"><textarea class="cdk-textarea-autosize" placeholder="Nachricht schreiben"></textarea></div>
<script>
window.onload = async () => {
  const textarea = document.querySelector('textarea');
  const measure = { _textareaElement:textarea, _platform:{FIREFOX:true}, _hasFocus:true,
    ${measurement}
  };
  const lineHeight = parseFloat(getComputedStyle(textarea).lineHeight);
  textarea.style.minHeight = lineHeight + 'px';
  textarea.style.maxHeight = lineHeight * 5 + 'px';
  textarea.focus();
  const failures = [];
  let checks = 0;
  let grew = false;
  let capped = false;
  let shrank = false;
  for (const width of [282,283,300,320,360,375,390,414,768,800]) {
    textarea.parentElement.style.width = width + 'px';
    for (const sample of ['i', 'W', 'hello ', 'Nachricht ', '🙂']) {
      for (let length=1; length<=150; length++) {
        textarea.value = sample.repeat(length);
        textarea.style.height = measure._measureScrollHeight() + 'px';
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
        const height = textarea.clientHeight;
        const fullHeight = textarea.scrollHeight;
        const maxHeight = Math.round(lineHeight * 5);
        checks++;
        if (fullHeight > height + 1 && height < maxHeight - 1 && failures.length < 10) {
          failures.push({width,sample,length,height,fullHeight});
        }
        grew ||= height > lineHeight * 1.5;
        capped ||= height >= maxHeight - 1 && fullHeight > height;
      }
      textarea.value = '';
      textarea.style.height = measure._measureScrollHeight() + 'px';
      shrank ||= Math.abs(textarea.clientHeight - lineHeight) <= 1;
    }
  }
  await fetch('http://127.0.0.1:${address.port}', {
    method:'POST', body:JSON.stringify({checks,failures,grew,capped,shrank})
  });
};
</script>`;
const htmlPath = join(work, 'check.html');
await writeFile(htmlPath, html);
const firefox = process.env.FIREFOX_BIN ?? (process.platform === 'win32'
  ? 'C:\\Program Files\\Mozilla Firefox\\firefox.exe' : 'firefox');
const browser = spawn(firefox, ['--headless', '--no-remote', '--profile', join(work, 'profile'),
  '--screenshot', join(work, 'check.png'), '--window-size', '1000,900', pathToFileURL(htmlPath).href],
{ windowsHide:true, stdio:'ignore' });
let timer: ReturnType<typeof setTimeout> | undefined;
try {
  const outcome = await Promise.race([result, new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('Firefox check timed out.')), 60000);
    browser.once('error', reject);
  })]);
  console.log(JSON.stringify(outcome, null, 2));
  if (outcome.failures.length || !outcome.grew || !outcome.capped || !outcome.shrank) {
    throw new Error('Composer autosizing regression.');
  }
} finally {
  clearTimeout(timer);
  server.close();
  // The screenshot invocation exits itself after loading the page.
  await new Promise((resolve) => setTimeout(resolve, 1000));
  await rm(work, { recursive:true, force:true, maxRetries:5, retryDelay:200 });
}
