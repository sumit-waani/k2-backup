<script>
  import { toasts } from '../lib/stores.js';
  import { CheckCircle, AlertCircle, Info, X } from '@lucide/svelte';

  function iconForType(type) {
    if (type === 'success') return CheckCircle;
    if (type === 'error') return AlertCircle;
    return Info;
  }

  function dismiss(id) {
    toasts.update(t => t.filter(x => x.id !== id));
  }
</script>

{#if $toasts.length > 0}
  <div class="toast-container">
    {#each $toasts as toast (toast.id)}
      <div class="toast toast-{toast.type}" role="alert">
        <div class="toast-icon">
          <svelte:component this={iconForType(toast.type)} size={15} />
        </div>
        <span class="toast-msg">{toast.message}</span>
        <button class="toast-dismiss" onclick={() => dismiss(toast.id)} aria-label="Dismiss">
          <X size={13} />
        </button>
      </div>
    {/each}
  </div>
{/if}

<style>
  .toast-container {
    position: fixed;
    top: 12px;
    left: 12px;
    right: 12px;
    z-index: 200;
    display: flex;
    flex-direction: column;
    gap: 8px;
    pointer-events: none;
    max-width: 420px;
  }

  .toast {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
    line-height: 1.45;
    animation: fade-in 0.2s ease, slide-down 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    pointer-events: auto;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.06);
    word-break: break-word;
  }

  .toast-info {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    color: var(--color-text);
  }
  .toast-success {
    background: var(--color-success-bg);
    border: 1px solid color-mix(in srgb, var(--color-success) 30%, transparent);
    color: var(--color-success);
  }
  .toast-error {
    background: var(--color-error-bg);
    border: 1px solid color-mix(in srgb, var(--color-error) 30%, transparent);
    color: var(--color-error);
  }

  .toast-icon {
    flex-shrink: 0;
    margin-top: 1px;
  }

  .toast-msg {
    flex: 1;
    min-width: 0;
  }

  .toast-dismiss {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    opacity: 0.5;
    transition: opacity 0.15s;
    margin-top: -1px;
  }
  .toast-dismiss:hover { opacity: 1; }

  @keyframes slide-down {
    from { transform: translateY(-12px); opacity: 0; }
    to { transform: none; opacity: 1; }
  }
</style>
