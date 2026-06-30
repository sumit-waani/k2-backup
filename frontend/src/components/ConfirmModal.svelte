<script>
  import { confirmModal, closeConfirm } from '../lib/stores.js';
  import { AlertTriangle } from '@lucide/svelte';

  let modal = $derived($confirmModal);
  let loading = $state(false);

  async function handleConfirm() {
    loading = true;
    try {
      await modal.onConfirm();
    } catch (e) {
      console.error(e);
    } finally {
      loading = false;
      closeConfirm();
    }
  }

  function handleBackdrop(e) {
    if (e.target === e.currentTarget && !loading) closeConfirm();
  }

  function handleKeydown(e) {
    if (e.key === 'Escape' && !loading) closeConfirm();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="confirm-overlay" onclick={handleBackdrop} role="dialog" aria-modal="true" tabindex="-1">
  <div class="confirm-modal" role="alertdialog">
    <div class="confirm-icon" class:danger={modal.variant === 'danger'}>
      <AlertTriangle size={20} />
    </div>
    <h3>{modal.title}</h3>
    <p>{modal.message}</p>
    <div class="confirm-actions">
      <button class="btn-cancel" onclick={closeConfirm} disabled={loading}>
        Cancel
      </button>
      <button
        class="btn-confirm"
        class:danger={modal.variant === 'danger'}
        onclick={handleConfirm}
        disabled={loading}
      >
        {#if loading}
          <span class="btn-spinner"></span>
        {:else}
          Confirm
        {/if}
      </button>
    </div>
  </div>
</div>

<style>
  .confirm-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 150;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    animation: fade-overlay 0.15s ease;
    -webkit-backdrop-filter: blur(4px);
    backdrop-filter: blur(4px);
  }

  .confirm-modal {
    background: var(--color-surface);
    border-radius: 16px;
    padding: 24px;
    max-width: 340px;
    width: 100%;
    text-align: center;
    animation: fade-in 0.2s ease;
    box-shadow: 0 8px 32px rgba(0,0,0,0.12);
  }

  .confirm-icon {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    background: var(--color-warning-bg);
    color: var(--color-warning);
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 14px;
  }
  .confirm-icon.danger {
    background: var(--color-error-bg);
    color: var(--color-error);
  }

  h3 {
    font-size: 15px;
    font-weight: 700;
    margin: 0 0 6px;
    letter-spacing: -0.01em;
  }

  p {
    font-size: 13px;
    color: var(--color-text-secondary);
    margin: 0 0 20px;
    line-height: 1.5;
  }

  .confirm-actions {
    display: flex;
    gap: 8px;
  }

  .btn-cancel {
    flex: 1;
    padding: 10px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    color: var(--color-text);
    transition: all 0.15s ease;
  }
  .btn-cancel:hover { background: var(--color-surface-hover); }
  .btn-cancel:disabled { opacity: 0.5; }

  .btn-confirm {
    flex: 1;
    padding: 10px;
    background: var(--color-accent);
    color: white;
    border: none;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    transition: opacity 0.15s ease;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .btn-confirm:hover { opacity: 0.9; }
  .btn-confirm.danger { background: var(--color-error); }
  .btn-confirm:disabled { opacity: 0.5; }

  .btn-spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
</style>
