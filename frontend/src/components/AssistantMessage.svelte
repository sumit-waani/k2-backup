<script>
  import { renderMarkdown } from '../lib/markdown.js';
  import ToolGroup from './ToolGroup.svelte';

  let { msg } = $props();

  // Parse content — handles all formats:
  // 1. Rich array (streaming): [{type:'text',...}, {type:'tool_call',...}]
  // 2. JSON string (from DB): '{"content":[...]}' 
  // 3. Plain text (legacy/simple): "hello world"
  let parts = $derived.by(() => {
    let raw = msg.content;

    // If it's a string, try to parse as JSON first
    if (typeof raw === 'string') {
      if (!raw) return [];
      try {
        const parsed = JSON.parse(raw);
        // Rich format: {"content": [...parts]}
        if (parsed && typeof parsed === 'object' && Array.isArray(parsed.content)) {
          return parsed.content;
        }
        // Legacy JSON format
        if (parsed && typeof parsed === 'object' && parsed.role) {
          return parsed.content ? [{ type: 'text', text: String(parsed.content) }] : [];
        }
      } catch {
        // Not JSON — plain text
      }
      return [{ type: 'text', text: raw }];
    }

    // Already an array (streaming state)
    if (Array.isArray(raw)) {
      return raw;
    }

    return [];
  });

  // Group tool_call + tool_result into renderable tool groups.
  // Handles both streaming format (tool_call with _result inline)
  // and stored format (tool_call + tool_result as siblings in DB).
  let segments = $derived.by(() => {
    // First pass: build result map from tool_result entries
    const resultMap = {};
    for (const part of parts) {
      if (part.type === 'tool_result' && part.id) {
        resultMap[part.id] = part.output || '';
      }
    }

    // Second pass: merge results into tool_calls and filter out tool_results
    // This makes tool_calls consecutive for proper grouping
    const cleaned = [];
    for (const part of parts) {
      if (part.type === 'tool_result') continue; // skip — already in resultMap
      if (part.type === 'tool_call') {
        const tc = { ...part };
        // Merge result from stored format (tool_result sibling)
        if (!tc._result && resultMap[tc.id]) {
          tc._result = resultMap[tc.id];
        }
        // All persisted tool calls are completed
        if (tc._result !== undefined && tc._result !== null) {
          tc._running = false;
        }
        cleaned.push(tc);
      } else {
        cleaned.push(part);
      }
    }

    // Third pass: group consecutive tool_calls into tool groups
    const result = [];
    let i = 0;
    while (i < cleaned.length) {
      const part = cleaned[i];
      if (part.type === 'text' && part.text) {
        result.push({ type: 'text', text: part.text });
        i++;
      } else if (part.type === 'tool_call') {
        const tools = [];
        while (i < cleaned.length && cleaned[i].type === 'tool_call') {
          tools.push(cleaned[i]);
          i++;
        }
        result.push({ type: 'tools', tools });
      } else if (part.type === 'review') {
        result.push(part);
        i++;
      } else {
        i++;
      }
    }
    return result;
  });

  let isStreaming = $derived(!!msg._streaming);
</script>

<div class="msg-assistant" class:streaming={isStreaming}>
  <div class="msg-label">kaptaan</div>
  <div class="msg-content">
    {#each segments as segment, si}
      {#if segment.type === 'text'}
        <div class="text-block md">{@html renderMarkdown(segment.text)}</div>
      {:else if segment.type === 'tools'}
        <ToolGroup tools={segment.tools} />
      {:else if segment.type === 'review'}
        <div class="review-block" class:running={segment.status === 'running'} class:approved={segment.status === 'approved'} class:rejected={segment.status === 'rejected'} class:skipped={segment.status === 'skipped'}>
          <div class="review-header">
            <span class="review-icon">{segment.status === 'running' ? '🔍' : segment.status === 'approved' ? '✅' : segment.status === 'rejected' ? '❌' : '⏭️'}</span>
            <span class="review-title">
              {#if segment.status === 'running'}
                Code Review — Round {segment.round}/{segment.maxRounds}
              {:else if segment.status === 'approved'}
                {#if segment.forced}Review Forced Through{:else}Review Approved{/if}
              {:else if segment.status === 'rejected'}
                Review Rejected — Round {segment.round}/{segment.maxRounds}
              {:else if segment.status === 'skipped'}
                Review Skipped
              {/if}
            </span>
          </div>
          {#if segment.feedback}
            <div class="review-feedback">{segment.feedback}</div>
          {/if}
          {#if segment.issues && segment.issues.length > 0}
            <ul class="review-issues">
              {#each segment.issues as issue}
                <li>{issue}</li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}
    {/each}
    {#if isStreaming && segments.length === 0}
      <div class="thinking-dots">
        <span></span><span></span><span></span>
      </div>
    {/if}
  </div>
</div>

<style>
  .msg-assistant {
    display: flex;
    flex-direction: column;
    gap: 4px;
    animation: fade-in 0.2s ease;
    padding-bottom: 12px;
  }

  .msg-label {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--color-text-muted);
    padding-left: 2px;
    font-weight: 600;
  }

  .msg-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .text-block {
    padding: 0 2px;
  }

  /* Thinking dots */
  .thinking-dots {
    display: flex;
    gap: 4px;
    padding: 8px 0;
  }
  .thinking-dots span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-text-muted);
    animation: pulse-dot 1.2s ease-in-out infinite;
  }
  .thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
  .thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

  /* Review block */
  .review-block {
    border: 1px solid var(--color-border);
    border-radius: 12px;
    overflow: hidden;
    font-size: 12px;
  }
  .review-block.running {
    border-color: var(--color-accent);
    background: var(--color-surface-alt);
  }
  .review-block.approved {
    border-color: var(--color-success);
    background: var(--color-surface-alt);
  }
  .review-block.rejected {
    border-color: var(--color-error);
    background: var(--color-surface-alt);
  }
  .review-block.skipped {
    border-color: var(--color-border);
    background: var(--color-surface-alt);
    opacity: 0.7;
  }
  .review-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    font-weight: 600;
    font-size: 12px;
  }
  .review-block.running .review-header {
    background: color-mix(in srgb, var(--color-accent) 8%, transparent);
  }
  .review-block.approved .review-header {
    background: color-mix(in srgb, var(--color-success) 8%, transparent);
  }
  .review-block.rejected .review-header {
    background: color-mix(in srgb, var(--color-error) 8%, transparent);
  }
  .review-block.skipped .review-header {
    background: color-mix(in srgb, var(--color-text-muted) 8%, transparent);
  }
  .review-icon { font-size: 14px; }
  .review-title { color: var(--color-text); }
  .review-feedback {
    padding: 8px 12px;
    color: var(--color-text-secondary);
    line-height: 1.5;
    border-top: 1px solid var(--color-border);
    white-space: pre-wrap;
  }
  .review-issues {
    margin: 0;
    padding: 4px 12px 10px 28px;
    color: var(--color-text-secondary);
    line-height: 1.6;
  }
  .review-issues li {
    padding: 2px 0;
  }
</style>
