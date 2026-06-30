<script>
  import { messages } from '../lib/stores.js';
  import UserMessage from './UserMessage.svelte';
  import AssistantMessage from './AssistantMessage.svelte';
</script>

<div class="message-list">
  {#each $messages as msg (msg.id)}
    {#if msg.role === 'user'}
      <UserMessage {msg} />
    {:else if msg.role === 'assistant'}
      <AssistantMessage {msg} />
    {/if}
  {/each}
</div>

<style>
  .message-list {
    display: flex;
    flex-direction: column;
    padding: 16px 14px;
    gap: 4px;
  }
</style>
