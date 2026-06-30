import { marked } from 'marked';
import DOMPurify from 'dompurify';

marked.setOptions({ gfm: true, breaks: true });

// Custom renderer for code blocks with copy button
const renderer = new marked.Renderer();
renderer.code = function({ text, lang }) {
  const langLabel = lang ? `<span class="code-lang">${lang}</span>` : '';
  return `<div class="code-block">${langLabel}<button class="copy-btn" onclick="window.__copyCode(this)" aria-label="Copy code"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button><pre><code>${DOMPurify.sanitize(text)}</code></pre></div>`;
};

marked.use({ renderer });

// Global copy function
if (typeof window !== 'undefined') {
  window.__copyCode = function(btn) {
    const code = btn.parentElement.querySelector('code');
    if (code) {
      navigator.clipboard.writeText(code.textContent).then(() => {
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
          btn.classList.remove('copied');
        }, 2000);
      });
    }
  };
}

export function renderMarkdown(text) {
  if (!text) return '';
  return DOMPurify.sanitize(marked.parse(text));
}
