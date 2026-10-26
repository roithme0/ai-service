const INLINE_TOKEN =
  /(`[^`\n]+`)|(\[([^\]\n]+)\]\(([^)\s]+)\))|(\*\*([^*\n]+)\*\*)|(\*([^*\n]+)\*)/g;
const SAFE_LINK = /^(?:https?:\/\/|mailto:|\/(?!\/)|#)/i;

export function renderAssistantMarkdown(markdown: string): string {
  const lines = markdown.replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n');
  const html: string[] = [];
  let listType: 'ul' | 'ol' | undefined;
  let codeFence = false;
  let codeLines: string[] = [];

  const closeList = (): void => {
    if (listType !== undefined) {
      html.push(`</${listType}>`);
      listType = undefined;
    }
  };

  for (const line of lines) {
    if (line.trimStart().startsWith('```')) {
      closeList();
      if (codeFence) {
        html.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
        codeLines = [];
      }
      codeFence = !codeFence;
      continue;
    }

    if (codeFence) {
      codeLines.push(line);
      continue;
    }

    const unordered = line.match(/^\s*[-+]\s+(.+)$/);
    if (unordered !== null) {
      if (listType !== 'ul') {
        closeList();
        html.push('<ul>');
        listType = 'ul';
      }
      html.push(`<li>${renderInline(unordered[1])}</li>`);
      continue;
    }

    const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
    if (ordered !== null) {
      if (listType !== 'ol') {
        closeList();
        html.push('<ol>');
        listType = 'ol';
      }
      html.push(`<li>${renderInline(ordered[1])}</li>`);
      continue;
    }

    closeList();
    if (line.trim() === '') {
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading !== null) {
      const level = heading[1].length + 2;
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }

    const quote = line.match(/^>\s?(.+)$/);
    if (quote !== null) {
      html.push(`<blockquote>${renderInline(quote[1])}</blockquote>`);
      continue;
    }

    html.push(`<p>${renderInline(line)}</p>`);
  }

  closeList();
  if (codeFence) {
    html.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
  }

  return html.join('');
}

function renderInline(value: string): string {
  const html: string[] = [];
  let lastIndex = 0;

  for (const match of value.matchAll(INLINE_TOKEN)) {
    const index = match.index;
    html.push(escapeHtml(value.slice(lastIndex, index)));

    if (match[1] !== undefined) {
      html.push(`<code>${escapeHtml(match[1].slice(1, -1))}</code>`);
    } else if (match[2] !== undefined) {
      const label = escapeHtml(match[3]);
      const url = match[4];
      html.push(SAFE_LINK.test(url) ? `<a href="${escapeHtml(url)}">${label}</a>` : label);
    } else if (match[5] !== undefined) {
      html.push(`<strong>${escapeHtml(match[6])}</strong>`);
    } else if (match[7] !== undefined) {
      html.push(`<em>${escapeHtml(match[8])}</em>`);
    }

    lastIndex = index + match[0].length;
  }

  html.push(escapeHtml(value.slice(lastIndex)));
  return html.join('');
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
