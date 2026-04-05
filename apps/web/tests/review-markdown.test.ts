import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ReviewMarkdown, stripHtmlComments } from '../components/review/ReviewMarkdown';

describe('ReviewMarkdown', () => {
  it('renders GFM tables as HTML tables', () => {
    const markdown = [
      '## Glossary of Terms',
      '',
      '| TERM | DEFINITION |',
      '| --- | --- |',
      '| CFM | Cubic Feet per Minute |',
      '| LNG | Liquefied Natural Gas |',
    ].join('\n');

    const html = renderToStaticMarkup(createElement(ReviewMarkdown, { content: markdown }));

    expect(html).toContain('<table');
    expect(html).toContain('<thead');
    expect(html).toContain('<tbody');
    expect(html).toContain('<th');
    expect(html).toContain('Glossary of Terms');
    expect(html).toContain('Cubic Feet per Minute');
  });

  it('removes HTML comments before rendering', () => {
    const cleaned = stripHtmlComments('<!-- hidden -->\n| A | B |\n| - | - |\n| 1 | 2 |');

    expect(cleaned).not.toContain('hidden');
    expect(cleaned).toContain('| A | B |');
  });
});