<script>
  import { tick } from 'svelte';
  import { messages, agentStatus, agentError, sendMessage, clearMessages, showSettings, showConfirm, refreshState, isRefreshing } from '../lib/stores.js';
  import MessageList from './MessageList.svelte';
  import Composer from './Composer.svelte';
  import { Settings, Trash2, RefreshCw } from '@lucide/svelte';

  let msgsEl = $state(null);
  let autoScroll = $state(true);

  $effect(() => {
    // Trigger on any message change
    $messages;
    if (autoScroll && msgsEl) {
      tick().then(() => {
        msgsEl.scrollTop = msgsEl.scrollHeight;
      });
    }
  });

  function handleScroll() {
    if (!msgsEl) return;
    const { scrollTop, scrollHeight, clientHeight } = msgsEl;
    autoScroll = scrollHeight - scrollTop - clientHeight < 80;
  }

  function handleSend(content) {
    autoScroll = true;
    sendMessage(content);
  }

  function handleClear() {
    showConfirm(
      'Clear conversation',
      'This will delete all messages and run history. This cannot be undone.',
      async () => {
        await clearMessages();
        autoScroll = true;
      }
    );
  }

  function handleRefresh() {
    autoScroll = true;
    refreshState();
  }
</script>

<div class="chat-root">
  <!-- Header -->
  <header class="chat-header">
    <div class="header-left">
      <div class="header-brand">kaptaan</div>
      <div class="header-status" class:running={$agentStatus === 'running'} class:error={$agentStatus === 'error'}>
        <span class="status-dot"></span>
        <span class="status-text">
          {#if $agentStatus === 'running'}thinking{:else if $agentStatus === 'error'}error{:else}ready{/if}
        </span>
      </div>
    </div>
    <div class="header-actions">
      <button
        class="icon-btn"
        class:spinning={$isRefreshing}
        onclick={handleRefresh}
        disabled={$isRefreshing}
        aria-label="Refresh"
        title="Reconnect and reload"
      >
        <RefreshCw size={16} strokeWidth={1.75} />
      </button>
      <button class="icon-btn" onclick={handleClear} aria-label="Clear conversation" title="Clear conversation">
        <Trash2 size={16} strokeWidth={1.75} />
      </button>
      <button class="icon-btn" onclick={() => showSettings.set(true)} aria-label="Settings" title="Settings">
        <Settings size={16} strokeWidth={1.75} />
      </button>
    </div>
  </header>

  <!-- Messages -->
  <div class="chat-messages" bind:this={msgsEl} onscroll={handleScroll}>
    {#if $messages.length === 0}
      <div class="empty-state">
        <div class="empty-icon">k</div>
        <div class="empty-title">kaptaan</div>
        <div class="empty-sub">send a message to begin</div>
      </div>
    {:else}
      <MessageList />
    {/if}
  </div>

  <!-- Composer -->
  <Composer onSend={handleSend} disabled={$agentStatus === 'running'} />
</div>

<style>
  .chat-root {
    display: flex;
    flex-direction: column;
    height: 100vh;
    height: 100dvh;
    background: var(--color-surface);
    overflow: hidden;
    max-width: 100vw;
  }

  /* Header */
  .chat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    border-bottom: 1px solid var(--color-border);
    background: var(--color-surface);
    flex-shrink: 0;
    position: relative;
    z-index: 10;
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .header-brand {
    font-size: 15px;
    font-weight: 700;
    letter-spacing: -0.03em;
  }

  .header-status {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 8px;
    border-radius: 999px;
    border: 1px solid var(--color-border);
    background: var(--color-surface-alt);
  }

  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-text-muted);
    transition: background 0.2s ease;
  }

  .header-status.running .status-dot {
    background: var(--color-accent);
    animation: pulse-dot 1.2s ease-in-out infinite;
  }

  .header-status.error .status-dot {
    background: var(--color-error);
  }

  .status-text {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--color-text-secondary);
    font-weight: 600;
  }

  .header-actions {
    display: flex;
    gap: 6px;
  }

  .icon-btn {
    width: 34px;
    height: 34px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 10px;
    border: 1px solid var(--color-border);
    background: var(--color-surface);
    color: var(--color-text-secondary);
    transition: all 0.15s ease;
  }
  .icon-btn:hover {
    background: var(--color-surface-hover);
    color: var(--color-text);
    border-color: var(--color-border-strong);
  }
  .icon-btn:active {
    transform: scale(0.95);
  }
  .icon-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .icon-btn.spinning {
    color: var(--color-accent);
    border-color: var(--color-accent);
    pointer-events: none;
  }
  .icon-btn.spinning :global(svg) {
    animation: spin 0.8s linear infinite;
  }

  /* Messages */
  .chat-messages {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior-y: contain;
  }

  /* Empty state */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    padding: 40px 20px;
    text-align: center;
    animation: fade-in 0.4s ease;
  }

  .empty-icon {
    width: 64px;
    height: 64px;
    border-radius: 20px;
    background: var(--color-surface-alt);
    border: 1px solid var(--color-border);
    color: var(--color-text-muted);
    font-family: var(--font-mono);
    font-size: 28px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;
  }

  .empty-title {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.03em;
    margin-bottom: 6px;
  }

  .empty-sub {
    font-size: 13px;
    color: var(--color-text-muted);
  }
</style>
