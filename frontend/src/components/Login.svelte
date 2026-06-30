<script>
  import { login, showToast } from '../lib/stores.js';

  let username = $state('');
  let password = $state('');
  let error = $state('');
  let loading = $state(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    error = '';
    loading = true;
    try {
      await login(username.trim(), password);
    } catch (e) {
      error = e.message || 'Login failed';
    } finally {
      loading = false;
    }
  }
</script>

<div class="login-wrap">
  <form class="login-card" onsubmit={handleSubmit}>
    <div class="login-brand">
      <div class="login-icon">k</div>
      <h1>kaptaan</h1>
      <p>your technical co-pilot</p>
    </div>

    <div class="login-fields">
      <label>
        <span>Username</span>
        <input
          type="text"
          bind:value={username}
          placeholder="Enter username"
          autocomplete="username"
          disabled={loading}
        />
      </label>
      <label>
        <span>Password</span>
        <input
          type="password"
          bind:value={password}
          placeholder="Enter password"
          autocomplete="current-password"
          disabled={loading}
        />
      </label>
    </div>

    {#if error}
      <div class="login-error">{error}</div>
    {/if}

    <button type="submit" class="login-btn" disabled={loading || !username.trim() || !password}>
      {#if loading}
        <span class="btn-spinner"></span>
      {:else}
        Sign in
      {/if}
    </button>
  </form>
</div>

<style>
  .login-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100dvh;
    padding: 20px;
    background: var(--color-surface);
  }

  .login-card {
    width: 100%;
    max-width: 340px;
    animation: fade-in 0.3s ease;
  }

  .login-brand {
    text-align: center;
    margin-bottom: 36px;
  }

  .login-icon {
    width: 56px;
    height: 56px;
    border-radius: 16px;
    background: var(--color-accent);
    color: white;
    font-family: var(--font-mono);
    font-size: 24px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 16px;
  }

  h1 {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.03em;
    margin: 0 0 4px;
  }

  p {
    font-size: 13px;
    color: var(--color-text-muted);
    margin: 0;
  }

  .login-fields {
    display: flex;
    flex-direction: column;
    gap: 14px;
    margin-bottom: 20px;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  label span {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--color-text-secondary);
    font-weight: 600;
  }

  .login-error {
    background: var(--color-error-bg);
    color: var(--color-error);
    padding: 10px 12px;
    border-radius: 10px;
    font-size: 12px;
    margin-bottom: 14px;
    border: 1px solid color-mix(in srgb, var(--color-error) 20%, transparent);
  }

  .login-btn {
    width: 100%;
    padding: 12px;
    background: var(--color-accent);
    color: white;
    border: none;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s ease, transform 0.1s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }
  .login-btn:hover { opacity: 0.9; }
  .login-btn:active { transform: scale(0.98); }
  .login-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .btn-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
</style>
