<script>
  import { onMount } from 'svelte';
  import { isAuthenticated, checkAuth, loadMessages, resumeActiveRun, toasts, confirmModal, closeConfirm } from './lib/stores.js';
  import Login from './components/Login.svelte';
  import Chat from './components/Chat.svelte';
  import Settings from './components/Settings.svelte';
  import Toast from './components/Toast.svelte';
  import ConfirmModal from './components/ConfirmModal.svelte';

  let loading = $state(true);

  onMount(async () => {
    const authed = await checkAuth();
    if (authed) {
      await loadMessages();
      await resumeActiveRun();
    }
    loading = false;
  });
</script>

{#if loading}
  <div class="loading-screen">
    <div class="loading-spinner"></div>
  </div>
{:else if $isAuthenticated}
  <Chat />
  <Settings />
{:else}
  <Login />
{/if}

<Toast />
{#if $confirmModal}
  <ConfirmModal />
{/if}

<style>
  .loading-screen {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100dvh;
    background: var(--color-surface);
  }
  .loading-spinner {
    width: 24px;
    height: 24px;
    border: 2.5px solid var(--color-border);
    border-top-color: var(--color-accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }
</style>
