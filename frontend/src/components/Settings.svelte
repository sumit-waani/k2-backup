<script>
  import { showSettings, showToast, logout, showConfirm } from '../lib/stores.js';
  import { api } from '../lib/api.js';
  import { X, Save, LogOut, Plus, Trash2 } from '@lucide/svelte';

  let settings = $state(null);
  let saving = $state(false);

  let llm1_url = $state('');
  let llm1_model = $state('');
  let llm1_api_key = $state('');
  let firecrawl_key = $state('');
  let daytona_api_key = $state('');
  let system_prompt = $state('');
  let memory = $state('');

  let newUsername = $state('');
  let newPassword = $state('');
  let sandboxId = $state('');
  let sandbox_cpu = $state('4');
  let sandbox_memory = $state('8');
  let sandbox_disk = $state('10');
  let vps_host = $state('');
  let vps_port = $state('22');
  let vps_username = $state('');
  let vps_password = $state('');
  let vps_ssh_key = $state('');
  let vps2_host = $state('');
  let vps2_port = $state('22');
  let vps2_username = $state('');
  let vps2_password = $state('');
  let vps2_ssh_key = $state('');
  let vps2Testing = $state(false);
  let vps2TestResult = $state(null);
  let github_repo_url = $state('');
  let github_pat = $state('');
  let scratchpad = $state('');
  let vpsTesting = $state(false);
  let vpsTestResult = $state(null);

  $effect(() => {
    if ($showSettings) loadSettings();
  });

  async function loadSettings() {
    try {
      const { settings: s } = await api.settings();
      settings = s;
      llm1_url = s.llm1_url || '';
      llm1_model = s.llm1_model || '';
      llm1_api_key = '';
      firecrawl_key = '';
      daytona_api_key = '';
      system_prompt = s.system_prompt || '';
      memory = s.memory || '';
      sandboxId = s.sandbox_id || '';
      sandbox_cpu = String(s.sandbox_cpu || '4');
      sandbox_memory = String(s.sandbox_memory || '8');
      sandbox_disk = String(s.sandbox_disk || '10');
      vps_host = s.vps_host || '';
      vps_port = s.vps_port || '22';
      vps_username = s.vps_username || '';
      vps_password = '';
      vps_ssh_key = '';
      vps2_host = s.vps2_host || '';
      vps2_port = s.vps2_port || '22';
      vps2_username = s.vps2_username || '';
      vps2_password = '';
      vps2_ssh_key = '';
      github_repo_url = s.github_repo_url || '';
      github_pat = '';
      scratchpad = s.scratchpad || '';
      vpsTestResult = null;
    } catch (e) {
      if (e.status === 401) showSettings.set(false);
    }
  }

  function isMasked(v) { return v && /^•+$/.test(v); }

  async function handleSave() {
    saving = true;
    try {
      const patch = {};
      if (llm1_url) patch.llm1_url = llm1_url;
      if (llm1_model) patch.llm1_model = llm1_model;
      if (llm1_api_key && !isMasked(llm1_api_key)) patch.llm1_api_key = llm1_api_key;
      if (firecrawl_key && !isMasked(firecrawl_key)) patch.firecrawl_key = firecrawl_key;
      if (daytona_api_key && !isMasked(daytona_api_key)) patch.daytona_api_key = daytona_api_key;
      if (system_prompt !== undefined) patch.system_prompt = system_prompt;
      if (memory !== undefined) patch.memory = memory;
      if (vps_host) patch.vps_host = vps_host;
      if (vps_port) patch.vps_port = vps_port;
      if (vps_username) patch.vps_username = vps_username;
      // VPS auth: only one method at a time — explicitly clear the other
      const hasPassword = vps_password && !isMasked(vps_password);
      const hasKey = vps_ssh_key && !isMasked(vps_ssh_key);
      if (hasPassword) { patch.vps_password = vps_password; patch.vps_ssh_key = ''; }
      else if (hasKey) { patch.vps_ssh_key = vps_ssh_key; patch.vps_password = ''; }
      if (vps2_host) patch.vps2_host = vps2_host;
      if (vps2_port) patch.vps2_port = vps2_port;
      if (vps2_username) patch.vps2_username = vps2_username;
      const hasPassword2 = vps2_password && !isMasked(vps2_password);
      const hasKey2 = vps2_ssh_key && !isMasked(vps2_ssh_key);
      if (hasPassword2) { patch.vps2_password = vps2_password; patch.vps2_ssh_key = ''; }
      else if (hasKey2) { patch.vps2_ssh_key = vps2_ssh_key; patch.vps2_password = ''; }
      if (github_repo_url) patch.github_repo_url = github_repo_url;
      if (github_pat && !isMasked(github_pat)) patch.github_pat = github_pat;
      if (scratchpad !== undefined) patch.scratchpad = scratchpad;
      // Sandbox specs
      if (sandbox_cpu) patch.sandbox_cpu = parseInt(sandbox_cpu, 10);
      if (sandbox_memory) patch.sandbox_memory = parseInt(sandbox_memory, 10);
      if (sandbox_disk) patch.sandbox_disk = parseInt(sandbox_disk, 10);
      const { settings: s } = await api.saveSettings(patch);
      settings = s;
      llm1_api_key = '';
      firecrawl_key = '';
      daytona_api_key = '';
      vps_password = '';
      vps_ssh_key = '';
      vps2_password = '';
      vps2_ssh_key = '';
      github_pat = '';
      showToast('Settings saved', 'success');
    } catch (e) {
      showToast(e.message, 'error');
    } finally {
      saving = false;
    }
  }

  async function handleSaveAccount() {
    const patch = {};
    if (newUsername.trim()) patch.username = newUsername.trim();
    if (newPassword) patch.password = newPassword;
    if (!Object.keys(patch).length) return;
    try {
      await api.saveCreds(patch);
      newUsername = '';
      newPassword = '';
      showToast('Account updated', 'success');
    } catch (e) {
      showToast(e.message, 'error');
    }
  }

  async function handleCreateSandbox() {
    try {
      // Save sandbox specs first so create uses latest values
      const specPatch = {};
      if (sandbox_cpu) specPatch.sandbox_cpu = parseInt(sandbox_cpu, 10);
      if (sandbox_memory) specPatch.sandbox_memory = parseInt(sandbox_memory, 10);
      if (sandbox_disk) specPatch.sandbox_disk = parseInt(sandbox_disk, 10);
      if (daytona_api_key && !isMasked(daytona_api_key)) specPatch.daytona_api_key = daytona_api_key;
      if (Object.keys(specPatch).length) await api.saveSettings(specPatch);

      const r = await api.createSandbox();
      sandboxId = r.sandbox_id || '';
      showToast('Sandbox created', 'success');
    } catch (e) {
      showToast(e.message, 'error', 6000);
    }
  }

  async function handleDeleteSandbox() {
    showConfirm('Delete sandbox', 'This will hard-delete the current sandbox. Files will be gone.', async () => {
      try {
        await api.deleteSandbox();
        sandboxId = '';
        showToast('Sandbox deleted', 'success');
      } catch (e) {
        showToast(e.message, 'error', 6000);
      }
    });
  }

  async function handleTestVps() {
    vpsTesting = true;
    vpsTestResult = null;
    try {
      // Save VPS creds first so test uses latest values
      const patch = {};
      if (vps_host) patch.vps_host = vps_host;
      if (vps_port) patch.vps_port = vps_port;
      if (vps_username) patch.vps_username = vps_username;
      const _hasPw = vps_password && !isMasked(vps_password);
      const _hasKey = vps_ssh_key && !isMasked(vps_ssh_key);
      if (_hasPw) { patch.vps_password = vps_password; patch.vps_ssh_key = ''; }
      else if (_hasKey) { patch.vps_ssh_key = vps_ssh_key; patch.vps_password = ''; }
      if (Object.keys(patch).length) await api.saveSettings(patch);

      const r = await api.testVps();
      vpsTestResult = r;
    } catch (e) {
      vpsTestResult = { ok: false, message: e.message };
    } finally {
      vpsTesting = false;
    }
  }

  async function handleClearVps() {
    showConfirm('Clear VPS credentials', 'This will remove all saved VPS connection details.', async () => {
      try {
        await api.saveSettings({
          vps_host: '', vps_port: '22', vps_username: '',
          vps_password: '', vps_ssh_key: ''
        });
        vps_host = ''; vps_port = '22'; vps_username = '';
        vps_password = ''; vps_ssh_key = '';
        vpsTestResult = null;
        if (settings) {
          settings.vps_host = ''; settings.vps_port = '22';
          settings.vps_username = ''; settings.vps_password = ''; settings.vps_ssh_key = '';
        }
        showToast('VPS credentials cleared', 'success');
      } catch (e) {
        showToast(e.message, 'error', 6000);
      }
    });
  }

  async function handleTestVps2() {
    vps2Testing = true;
    vps2TestResult = null;
    try {
      const patch = {};
      if (vps2_host) patch.vps2_host = vps2_host;
      if (vps2_port) patch.vps2_port = vps2_port;
      if (vps2_username) patch.vps2_username = vps2_username;
      const _hasPw = vps2_password && !isMasked(vps2_password);
      const _hasKey = vps2_ssh_key && !isMasked(vps2_ssh_key);
      if (_hasPw) { patch.vps2_password = vps2_password; patch.vps2_ssh_key = ''; }
      else if (_hasKey) { patch.vps2_ssh_key = vps2_ssh_key; patch.vps2_password = ''; }
      if (Object.keys(patch).length) await api.saveSettings(patch);

      const r = await api.testVps('vps2');
      vps2TestResult = r;
    } catch (e) {
      vps2TestResult = { ok: false, message: e.message };
    } finally {
      vps2Testing = false;
    }
  }

  async function handleClearVps2() {
    showConfirm('Clear VPS 2 credentials', 'This will remove all saved VPS 2 connection details.', async () => {
      try {
        await api.saveSettings({
          vps2_host: '', vps2_port: '22', vps2_username: '',
          vps2_password: '', vps2_ssh_key: ''
        });
        vps2_host = ''; vps2_port = '22'; vps2_username = '';
        vps2_password = ''; vps2_ssh_key = '';
        vps2TestResult = null;
        if (settings) {
          settings.vps2_host = ''; settings.vps2_port = '22';
          settings.vps2_username = ''; settings.vps2_password = ''; settings.vps2_ssh_key = '';
        }
        showToast('VPS 2 credentials cleared', 'success');
      } catch (e) {
        showToast(e.message, 'error', 6000);
      }
    });
  }

  function handleClose() { showSettings.set(false); }

  function handleBackdropClick(e) {
    if (e.target === e.currentTarget) handleClose();
  }

  async function handleLogout() {
    handleClose();
    await logout();
  }
</script>

{#if $showSettings}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="settings-overlay" onclick={handleBackdropClick} role="dialog" aria-modal="true" tabindex="-1">
    <div class="settings-sheet">
      <div class="settings-header">
        <h2>Settings</h2>
        <button class="close-btn" onclick={handleClose} aria-label="Close">
          <X size={18} />
        </button>
      </div>

      <div class="settings-body">
        <section class="settings-section">
          <h3>LLM</h3>
          <label>
            <span>Base URL</span>
            <input type="text" bind:value={llm1_url} placeholder="https://api.openai.com/v1" />
          </label>
          <label>
            <span>Model</span>
            <input type="text" bind:value={llm1_model} placeholder="gpt-4o" />
          </label>
          <label>
            <span>API Key</span>
            <input type="password" bind:value={llm1_api_key} placeholder={settings?.llm1_api_key ? '••••••••' : 'sk-…'} />
          </label>
        </section>

        <section class="settings-section">
          <h3>Firecrawl</h3>
          <label>
            <span>API Key</span>
            <input type="password" bind:value={firecrawl_key} placeholder={settings?.firecrawl_key ? '••••••••' : 'fc-…'} />
          </label>
        </section>

        <section class="settings-section">
          <h3>System Prompt</h3>
          <label>
            <span>Loaded fresh on every request</span>
            <textarea bind:value={system_prompt} rows="5" placeholder="You are Kaptaan…"></textarea>
          </label>
        </section>

        <section class="settings-section">
          <h3>Memory</h3>
          <label>
            <span>Markdown — project context, notes, etc.</span>
            <textarea bind:value={memory} rows="6" placeholder="# Project context…"></textarea>
          </label>
        </section>

        <section class="settings-section">
          <h3>VPS 1 (Remote Server)</h3>
          <div class="grid-2">
            <label>
              <span>Host</span>
              <input type="text" bind:value={vps_host} placeholder="13.235.154.101" />
            </label>
            <label>
              <span>Port</span>
              <input type="text" bind:value={vps_port} placeholder="22" />
            </label>
          </div>
          <label>
            <span>Username</span>
            <input type="text" bind:value={vps_username} placeholder="ubuntu" />
          </label>
          <label>
            <span>Password <small>(optional if using key)</small></span>
            <input type="password" bind:value={vps_password} placeholder={settings?.vps_password ? '••••••••' : 'leave empty if using key'} />
          </label>
          <label>
            <span>SSH Private Key <small>(optional if using password)</small></span>
            <textarea bind:value={vps_ssh_key} rows="4" placeholder={settings?.vps_ssh_key ? '••••••••' : '-----BEGIN RSA PRIVATE KEY-----\n...'}></textarea>
          </label>
          <div class="vps-test-row">
            <button class="btn-secondary" onclick={handleTestVps} disabled={vpsTesting || !vps_host}>
              {#if vpsTesting}
                Testing…
              {:else}
                Check Connection
              {/if}
            </button>
            <button class="btn-danger-sm" onclick={handleClearVps} disabled={!settings?.vps_host}>
              Clear VPS Creds
            </button>
            {#if vpsTestResult}
              <span class="vps-test-result" class:success={vpsTestResult.ok} class:fail={!vpsTestResult.ok}>
                {vpsTestResult.message}
              </span>
            {/if}
          </div>
        </section>

        <section class="settings-section">
          <h3>VPS 2 (Remote Server)</h3>
          <div class="grid-2">
            <label>
              <span>Host</span>
              <input type="text" bind:value={vps2_host} placeholder="10.0.0.1" />
            </label>
            <label>
              <span>Port</span>
              <input type="text" bind:value={vps2_port} placeholder="22" />
            </label>
          </div>
          <label>
            <span>Username</span>
            <input type="text" bind:value={vps2_username} placeholder="ubuntu" />
          </label>
          <label>
            <span>Password <small>(optional if using key)</small></span>
            <input type="password" bind:value={vps2_password} placeholder={settings?.vps2_password ? '••••••••' : 'leave empty if using key'} />
          </label>
          <label>
            <span>SSH Private Key <small>(optional if using password)</small></span>
            <textarea bind:value={vps2_ssh_key} rows="4" placeholder={settings?.vps2_ssh_key ? '••••••••' : '-----BEGIN RSA PRIVATE KEY-----\n...'}></textarea>
          </label>
          <div class="vps-test-row">
            <button class="btn-secondary" onclick={handleTestVps2} disabled={vps2Testing || !vps2_host}>
              {#if vps2Testing}
                Testing…
              {:else}
                Check Connection
              {/if}
            </button>
            <button class="btn-danger-sm" onclick={handleClearVps2} disabled={!settings?.vps2_host}>
              Clear VPS 2 Creds
            </button>
            {#if vps2TestResult}
              <span class="vps-test-result" class:success={vps2TestResult.ok} class:fail={!vps2TestResult.ok}>
                {vps2TestResult.message}
              </span>
            {/if}
          </div>
        </section>

        <section class="settings-section">
          <h3>Account</h3>
          <div class="grid-2">
            <label>
              <span>New Username</span>
              <input type="text" bind:value={newUsername} placeholder="leave empty to keep" autocomplete="off" />
            </label>
            <label>
              <span>New Password</span>
              <input type="password" bind:value={newPassword} placeholder="leave empty to keep" autocomplete="new-password" />
            </label>
          </div>
          <button class="btn-secondary" onclick={handleSaveAccount}>Update account</button>
        </section>

        <section class="settings-section">
          <h3>Daytona Sandbox</h3>
          <label>
            <span>API Key</span>
            <input type="password" bind:value={daytona_api_key} placeholder={settings?.daytona_api_key ? '••••••••' : 'dtn_…'} />
          </label>
          {#if !github_repo_url || !github_pat}
            <p class="hint warning">⚠ Set GitHub URL and PAT below before creating a sandbox.</p>
          {/if}
          <div class="sandbox-specs">
            <div class="grid-3">
              <label>
                <span>CPU Cores</span>
                <select bind:value={sandbox_cpu}>
                  <option value="2">2 cores</option>
                  <option value="4">4 cores</option>
                  <option value="8">8 cores</option>
                  <option value="16">16 cores</option>
                </select>
              </label>
              <label>
                <span>RAM (GB)</span>
                <select bind:value={sandbox_memory}>
                  <option value="4">4 GB</option>
                  <option value="8">8 GB</option>
                  <option value="16">16 GB</option>
                  <option value="32">32 GB</option>
                </select>
              </label>
              <label>
                <span>Disk (GB)</span>
                <select bind:value={sandbox_disk}>
                  <option value="10">10 GB</option>
                  <option value="20">20 GB</option>
                  <option value="50">50 GB</option>
                  <option value="100">100 GB</option>
                </select>
              </label>
            </div>
            <p class="hint">Resources are set at creation. Delete and recreate sandbox to change.</p>
          </div>
          <div class="sandbox-info">
            <span class="sandbox-label">Current sandbox</span>
            <span class="sandbox-id">{sandboxId || '(none)'}</span>
          </div>
          <div class="sandbox-actions">
            <button class="btn-secondary" onclick={handleCreateSandbox}>
              <Plus size={14} /> Create
            </button>
            <button class="btn-danger-text" onclick={handleDeleteSandbox}>
              <Trash2 size={14} /> Delete
            </button>
          </div>
        </section>

        <section class="settings-section">
          <h3>GitHub</h3>
          <label>
            <span>Repository URL</span>
            <input type="text" bind:value={github_repo_url} placeholder="https://github.com/user/repo.git" />
          </label>
          <label>
            <span>Personal Access Token</span>
            <input type="password" bind:value={github_pat} placeholder={settings?.github_pat ? '••••••••' : 'ghp_…'} />
          </label>
          <p class="hint">Required for sandbox creation. Repo is auto-cloned (branch: main) when sandbox is created.</p>
        </section>

        <section class="settings-section">
          <h3>Scratchpad</h3>
          <label>
            <span>Agent working notes — auto-used for multi-step tasks</span>
            <textarea bind:value={scratchpad} rows="4" placeholder="# Task plan / working notes…"></textarea>
          </label>
        </section>

        <section class="settings-section">
          <button class="btn-danger-text" onclick={handleLogout}>
            <LogOut size={14} /> Sign out
          </button>
        </section>
      </div>

      <div class="settings-footer">
        <button class="btn-primary" onclick={handleSave} disabled={saving}>
          {#if saving}
            <span class="btn-spinner"></span>
          {:else}
            <Save size={14} /> Save
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .settings-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    z-index: 100;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    animation: fade-overlay 0.2s ease;
    -webkit-backdrop-filter: blur(4px);
    backdrop-filter: blur(4px);
  }

  .settings-sheet {
    width: 100%;
    max-width: 500px;
    max-height: 90dvh;
    background: var(--color-surface);
    border-radius: 20px 20px 0 0;
    display: flex;
    flex-direction: column;
    animation: slide-up 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    overflow: hidden;
  }

  .settings-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--color-border);
    flex-shrink: 0;
  }
  .settings-header h2 {
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin: 0;
  }

  .close-btn {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    color: var(--color-text-secondary);
    transition: all 0.15s ease;
  }
  .close-btn:hover { background: var(--color-surface-hover); color: var(--color-text); }

  .settings-body {
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    gap: 24px;
    -webkit-overflow-scrolling: touch;
  }

  .settings-section h3 {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--color-text-muted);
    font-weight: 700;
    margin: 0 0 12px;
  }
  .settings-section label {
    display: flex;
    flex-direction: column;
    gap: 5px;
    margin-bottom: 10px;
  }
  .settings-section label span {
    font-size: 11px;
    color: var(--color-text-secondary);
    font-weight: 500;
  }

  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .grid-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 10px;
  }
  @media (max-width: 400px) {
    .grid-2 { grid-template-columns: 1fr; }
    .grid-3 { grid-template-columns: 1fr; }
  }

  .sandbox-specs {
    margin-bottom: 10px;
  }
  .sandbox-specs select {
    appearance: none;
    -webkit-appearance: none;
    background: var(--color-surface) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a3a3a3' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E") no-repeat right 12px center;
    border: 1px solid var(--color-border);
    padding: 10px 32px 10px 12px;
    border-radius: 10px;
    font-family: var(--font-mono);
    font-size: 13px;
    cursor: pointer;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
    width: 100%;
  }
  .sandbox-specs select:focus {
    border-color: var(--color-accent);
    box-shadow: 0 0 0 3px rgba(10, 10, 10, 0.06);
    outline: none;
  }

  .sandbox-info {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 0;
    font-size: 12px;
  }
  .sandbox-label { color: var(--color-text-muted); font-size: 11px; }
  .sandbox-id {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--color-text-secondary);
    background: var(--color-surface-alt);
    padding: 2px 6px;
    border-radius: 4px;
  }
  .vps-test-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 4px;
  }
  .vps-test-result {
    font-size: 13px;
    font-weight: 500;
  }
  .vps-test-result.success { color: #4ade80; }
  .vps-test-result.fail { color: #f87171; }
  .btn-danger-sm { background: #7f1d1d; color: #fca5a5; border: 1px solid #991b1b; border-radius: 6px; padding: 6px 12px; font-size: 12px; cursor: pointer; transition: background 0.15s; }
  .btn-danger-sm:hover { background: #991b1b; }
  .btn-danger-sm:disabled { opacity: 0.4; cursor: not-allowed; }

  .sandbox-actions { display: flex; gap: 8px; margin-top: 8px; }
  .hint {
    font-size: 11px;
    color: var(--color-text-muted);
    margin: 4px 0 0;
  }
  .hint.warning { color: var(--color-warning); }

  .btn-secondary {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border: 1px solid var(--color-border);
    background: var(--color-surface);
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-text);
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .btn-secondary:hover { background: var(--color-surface-hover); border-color: var(--color-border-strong); }
  .btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }

  .btn-danger-text {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    color: var(--color-error);
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .btn-danger-text:hover { background: var(--color-error-bg); border-color: color-mix(in srgb, var(--color-error) 20%, transparent); }

  .btn-primary {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
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
  }
  .btn-primary:hover { opacity: 0.9; }
  .btn-primary:active { transform: scale(0.98); }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }

  .btn-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }

  .settings-footer {
    padding: 12px 20px;
    border-top: 1px solid var(--color-border);
    flex-shrink: 0;
    background: var(--color-surface);
    padding-bottom: max(12px, env(safe-area-inset-bottom));
  }
</style>
