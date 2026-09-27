import { describe, expect, it } from 'vitest';
import { renderAssistantMarkdown } from './assistant-markdown';

describe('renderAssistantMarkdown', () => {
  it('renders supported conversational formatting', () => {
    const html = renderAssistantMarkdown(
      'A **bold** answer with [details](https://example.com).\n\n- one\n- two',
    );

    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<a href="https://example.com">details</a>');
    expect(html).toContain('<ul><li>one</li><li>two</li></ul>');
  });

  it('escapes raw HTML and does not create unsafe links', () => {
    const html = renderAssistantMarkdown('<img src=x onerror=alert(1)> [run](javascript:alert(1))');

    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;');
    expect(html).toContain('run');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('href=');
    expect(html).not.toContain('javascript:');
  });
});
