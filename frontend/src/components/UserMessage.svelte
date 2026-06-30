<script>
  let { msg } = $props();

  let text = $state('');

  $effect(() => {
    if (typeof msg.content === 'string') {
      text = msg.content;
    } else {
      text = String(msg.content || '');
    }
  });
</script>

<div class="msg-user">
  <div class="msg-label">you</div>
  {#if text}
    <div class="msg-bubble">{text}</div>
  {/if}
</div>

<style>
  .msg-user {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
    animation: fade-in 0.2s ease;
  }

  .msg-label {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--color-text-muted);
    padding-right: 4px;
    font-weight: 600;
  }

  .msg-bubble {
    background: var(--color-accent);
    color: white;
    padding: 10px 14px;
    border-radius: 16px 16px 4px 16px;
    max-width: 85%;
    font-size: 14px;
    line-height: 1.55;
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-wrap: anywhere;
  }
</style>
