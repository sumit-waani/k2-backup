<script>
  import { Send } from '@lucide/svelte';

  let { onSend, disabled = false } = $props();

  let input = $state('');
  let textarea = $state(null);

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      const isMobile = window.matchMedia('(pointer: coarse)').matches;
      if (!isMobile) {
        e.preventDefault();
        handleSend();
      }
    }
  }

  function handleSend() {
    const text = input.trim();
    if (!text) return;
    if (disabled) return;

    onSend(text);
    input = '';
    if (textarea) textarea.style.height = 'auto';
  }

  function autoResize() {
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 160) + 'px';
    }
  }
</script>

<div class="composer" role="region" aria-label="Message composer">
  <div class="composer-inner">
    <textarea
      bind:this={textarea}
      bind:value={input}
      oninput={autoResize}
      onkeydown={handleKeydown}
      placeholder="message kaptaan…"
      rows="1"
      {disabled}
    ></textarea>
    <button
      class="send-btn"
      onclick={handleSend}
      disabled={disabled || !input.trim()}
      aria-label="Send message"
    >
      <Send size={16} strokeWidth={2} />
    </button>
  </div>
  <div class="composer-hint">
    {#if disabled}
      <span class="hint-running">kaptaan is thinking…</span>
    {:else}
      <span>shift+enter for new line</span>
    {/if}
  </div>
</div>

<style>
  .composer {
    flex-shrink: 0;
    border-top: 1px solid var(--color-border);
    background: var(--color-surface);
    padding: 10px 14px;
    padding-bottom: max(10px, env(safe-area-inset-bottom));
  }

  .composer-inner {
    display: flex;
    align-items: flex-end;
    gap: 6px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 14px;
    padding: 4px 4px 4px 8px;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  .composer-inner:focus-within {
    border-color: var(--color-accent);
    box-shadow: 0 0 0 3px rgba(10, 10, 10, 0.06);
  }

  textarea {
    flex: 1;
    min-width: 0;
    border: none;
    background: transparent;
    resize: none;
    padding: 8px 0;
    font-size: 14px;
    line-height: 1.5;
    min-height: 24px;
    max-height: 160px;
    outline: none;
    font-family: var(--font-mono);
  }
  textarea:focus {
    box-shadow: none;
    border-color: transparent;
  }

  .send-btn {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: var(--color-accent);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: opacity 0.15s ease, transform 0.1s ease;
  }
  .send-btn:hover { opacity: 0.85; }
  .send-btn:active { transform: scale(0.92); }
  .send-btn:disabled { opacity: 0.3; cursor: not-allowed; }

  .composer-hint {
    text-align: center;
    padding-top: 6px;
    font-size: 10px;
    color: var(--color-text-muted);
  }

  .hint-running {
    color: var(--color-text-secondary);
    font-weight: 500;
  }
</style>
