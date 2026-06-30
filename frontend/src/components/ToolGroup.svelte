<script>
  import { ChevronRight, Wrench, Check, Loader2 } from '@lucide/svelte';

  let { tools } = $props();
  let expanded = $state(false);

  let runningCount = $derived(tools.filter(t => t._running).length);
  let totalCount = $derived(tools.length);
  let allDone = $derived(runningCount === 0);

  function truncateArgs(args) {
    if (!args) return '';
    try {
      const obj = JSON.parse(args);
      const vals = Object.values(obj);
      if (vals.length === 1 && typeof vals[0] === 'string') {
        const v = vals[0];
        return v.length > 80 ? v.slice(0, 80) + '…' : v;
      }
      return JSON.stringify(obj, null, 0).slice(0, 100) + (JSON.stringify(obj).length > 100 ? '…' : '');
    } catch {
      return args.length > 80 ? args.slice(0, 80) + '…' : args;
    }
  }

  function formatOutput(output) {
    if (!output) return '';
    if (output.length > 600) return output.slice(0, 600) + '\n… [truncated]';
    return output;
  }
</script>

<div class="tool-group" class:expanded>
  <button class="tool-header" onclick={() => expanded = !expanded}>
    <div class="tool-header-left">
      {#if !allDone}
        <span class="spin-icon-wrap"><Loader2 size={13} /></span>
      {:else}
        <Check size={13} />
      {/if}
      <span class="tool-count">
        {totalCount} tool{totalCount !== 1 ? 's' : ''}
        {#if !allDone}
          <span class="tool-running">({runningCount} running)</span>
        {/if}
      </span>
    </div>
    <span class="chevron-wrap" class:rotated={expanded}>
      <ChevronRight size={14} />
    </span>
  </button>

  {#if expanded}
    <div class="tool-list">
      {#each tools as tool}
        <div class="tool-item">
          <div class="tool-name">
            <Wrench size={11} />
            <span>{tool.name}</span>
            {#if tool._running}
              <span class="tool-badge running">running</span>
            {:else}
              <span class="tool-badge done">done</span>
            {/if}
          </div>
          {#if tool.arguments}
            <div class="tool-args">{truncateArgs(tool.arguments)}</div>
          {/if}
          {#if tool._result}
            <div class="tool-result">
              <pre>{formatOutput(tool._result)}</pre>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .tool-group {
    border: 1px solid var(--color-border);
    border-radius: 12px;
    overflow: hidden;
    background: var(--color-surface);
  }

  .tool-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 8px 12px;
    background: var(--color-surface-alt);
    font-size: 12px;
    color: var(--color-text-secondary);
    cursor: pointer;
    transition: background 0.15s ease;
    gap: 8px;
  }
  .tool-header:hover {
    background: var(--color-surface-hover);
  }

  .tool-header-left {
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .tool-count {
    font-weight: 600;
    color: var(--color-text);
    font-size: 11px;
  }

  .tool-running {
    font-weight: 400;
    color: var(--color-text-muted);
  }

  .spin-icon-wrap {
    display: flex;
    align-items: center;
    animation: spin 0.7s linear infinite;
  }

  .chevron-wrap {
    display: flex;
    align-items: center;
    transition: transform 0.2s ease;
    color: var(--color-text-muted);
  }
  .chevron-wrap.rotated {
    transform: rotate(90deg);
  }

  .tool-list {
    border-top: 1px solid var(--color-border);
  }

  .tool-item {
    padding: 10px 12px;
    border-bottom: 1px solid var(--color-border);
    font-size: 12px;
  }
  .tool-item:last-child {
    border-bottom: none;
  }

  .tool-name {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--color-text);
    margin-bottom: 4px;
  }

  .tool-badge {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 1px 5px;
    border-radius: 4px;
    font-weight: 600;
  }
  .tool-badge.running {
    background: var(--color-warning-bg);
    color: var(--color-warning);
  }
  .tool-badge.done {
    background: var(--color-success-bg);
    color: var(--color-success);
  }

  .tool-args {
    color: var(--color-text-muted);
    font-size: 11px;
    font-family: var(--font-mono);
    margin-bottom: 6px;
    word-break: break-all;
  }

  .tool-result {
    background: var(--color-surface-alt);
    border-radius: 8px;
    padding: 8px 10px;
    border: 1px solid var(--color-border);
    margin-top: 4px;
  }

  .tool-result pre {
    margin: 0;
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-wrap: anywhere;
    color: var(--color-text-secondary);
    max-height: 200px;
    overflow-y: auto;
  }
</style>
