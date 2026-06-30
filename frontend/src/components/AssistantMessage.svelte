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
</style>
