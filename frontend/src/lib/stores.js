import { writable, derived, get } from 'svelte/store';
import { api, streamRun } from './api.js';

// ── Auth ──
export const isAuthenticated = writable(false);
export const currentUser = writable(null);

// ── Messages ──
export const messages = writable([]);
export const agentStatus = writable('idle'); // 'idle' | 'running' | 'error'
export const agentError = writable(null);

// ── UI State ──
export const showSettings = writable(false);
export const toasts = writable([]);
export const confirmModal = writable(null); // { title, message, onConfirm, variant }
export const isRefreshing = writable(false);

let _activeAbort = null;
let _activeRunId = null;
let _lastSeq = -1;

// ── Toast helper ──
let toastId = 0;
export function showToast(message, type = 'info', duration = 3000) {
  const id = ++toastId;
  toasts.update(t => [...t, { id, message, type }]);
  setTimeout(() => {
    toasts.update(t => t.filter(x => x.id !== id));
  }, duration);
}

// ── Confirm helper ──
export function showConfirm(title, message, onConfirm, variant = 'danger') {
  confirmModal.set({ title, message, onConfirm, variant });
}

export function closeConfirm() {
  confirmModal.set(null);
}

// ── Auth actions ──
export async function checkAuth() {
  try {
    const { user } = await api.me();
    currentUser.set(user);
    isAuthenticated.set(true);
    return true;
  } catch {
    isAuthenticated.set(false);
    currentUser.set(null);
    return false;
  }
}

export async function login(username, password) {
  const { user } = await api.login(username, password);
  currentUser.set(user);
  isAuthenticated.set(true);
}

export async function logout() {
  try { await api.logout(); } catch {}
  isAuthenticated.set(false);
  currentUser.set(null);
  messages.set([]);
  cancelStream();
}

// ── Message actions ──
export async function loadMessages() {
  try {
    const { messages: msgs } = await api.messages();
    messages.set(msgs || []);
  } catch (e) {
    if (e.status === 401) {
      isAuthenticated.set(false);
    }
  }
}

export async function clearMessages() {
  try {
    await api.clearMessages();
    messages.set([]);
    showToast('Conversation cleared', 'success');
  } catch (e) {
    showToast('Failed to clear: ' + e.message, 'error');
  }
}

function cancelStream() {
  if (_activeAbort) {
    _activeAbort();
    _activeAbort = null;
  }
  _activeRunId = null;
  _lastSeq = -1;
}

// ── Refresh / Reconnect ──
export async function refreshState() {
  if (get(isRefreshing)) return;
  isRefreshing.set(true);
  try {
    // 1. Cancel any active stream
    cancelStream();
    agentStatus.set('idle');
    agentError.set(null);

    // 2. Check auth
    const authed = await checkAuth();
    if (!authed) {
      showToast('Session expired — please log in again', 'error');
      return;
    }

    // 3. Reload messages
    await loadMessages();

    // 4. Check for active run and resume if found
    await resumeActiveRun();

    showToast('Reconnected', 'success', 2000);
  } catch (e) {
    showToast('Refresh failed: ' + e.message, 'error');
  } finally {
    isRefreshing.set(false);
  }
}

// ── Send message + stream ──
export async function sendMessage(content) {
  const text = (typeof content === 'string' ? content : '').trim();
  if (!text) return;
  const apiPayload = text;
  const uiContent = text;

  // Add user message to UI immediately
  const userMsg = {
    id: crypto.randomUUID(),
    role: 'user',
    content: uiContent,
    created_at: new Date().toISOString(),
  };
  messages.update(m => [...m, userMsg]);
  agentStatus.set('running');
  agentError.set(null);

  try {
    const { run_id } = await api.startMessage(apiPayload);
    _activeRunId = run_id;
    _lastSeq = -1;

    // Create a placeholder for the streaming assistant message
    const assistantId = crypto.randomUUID();
    const assistantMsg = {
      id: assistantId,
      role: 'assistant',
      content: [{ type: 'text', text: '' }],
      _streaming: true,
      _runId: run_id,
    };
    messages.update(m => [...m, assistantMsg]);

    _activeAbort = streamRun(run_id, -1, {
      onEvent: (data) => handleStreamEvent(data, assistantId),
      onDone: () => handleStreamDone(assistantId),
      onError: (e) => handleStreamError(assistantId, e),
    });
  } catch (e) {
    agentStatus.set('error');
    agentError.set(e.message);
    showToast(e.message, 'error');
  }
}

function handleStreamEvent(data, assistantId) {
  const ev = data.event;
  _lastSeq = data.seq;

  if (!ev) return;

  messages.update(msgs => {
    const idx = msgs.findIndex(m => m.id === assistantId);
    if (idx === -1) return msgs;
    const msg = { ...msgs[idx] };
    let content = [...(msg.content || [])];

    if (ev.type === 'token') {
      const lastPart = content[content.length - 1];
      if (lastPart && lastPart.type === 'text') {
        content[content.length - 1] = { type: 'text', text: lastPart.text + ev.content };
      } else {
        content.push({ type: 'text', text: ev.content });
      }
    } else if (ev.type === 'reasoning') {
      // skip in main content
    } else if (ev.type === 'tool_call') {
      content.push({
        type: 'tool_call',
        id: ev.id,
        name: ev.name,
        arguments: ev.arguments,
        _result: null,
        _running: true,
      });
    } else if (ev.type === 'tool_result') {
      for (let i = content.length - 1; i >= 0; i--) {
        if (content[i].type === 'tool_call' && content[i].id === ev.id) {
          content[i] = { ...content[i], _result: ev.output, _running: false };
          break;
        }
      }
    } else if (ev.type === 'error') {
      agentError.set(ev.message);
      showToast(ev.message, 'error', 5000);
    } else if (ev.type === 'status') {
      agentStatus.set(ev.status);
    }

    msg.content = content;
    msgs = [...msgs];
    msgs[idx] = msg;
    return msgs;
  });
}

function handleStreamDone(assistantId) {
  _activeAbort = null;
  _activeRunId = null;

  messages.update(msgs => {
    const idx = msgs.findIndex(m => m.id === assistantId);
    if (idx !== -1) {
      msgs[idx] = { ...msgs[idx], _streaming: false };
    }
    return [...msgs];
  });

  setTimeout(async () => {
    try {
      const { messages: persisted } = await api.messages();
      if (persisted && persisted.length > 0) {
        messages.set(persisted);
      }
    } catch {}
  }, 300);

  agentStatus.set('idle');
}

function handleStreamError(assistantId, error) {
  _activeAbort = null;
  _activeRunId = null;
  agentStatus.set('error');
  agentError.set(error.message);
  showToast(error.message, 'error', 5000);

  messages.update(msgs => {
    const idx = msgs.findIndex(m => m.id === assistantId);
    if (idx !== -1) {
      msgs[idx] = { ...msgs[idx], _streaming: false };
    }
    return [...msgs];
  });
}

// ── Resume active run on page load ──
export async function resumeActiveRun() {
  try {
    const { run } = await api.activeRun();
    if (run && run.id && run.status === 'running') {
      _activeRunId = run.id;
      agentStatus.set('running');

      const assistantId = crypto.randomUUID();
      messages.update(m => [...m, {
        id: assistantId,
        role: 'assistant',
        content: [{ type: 'text', text: '' }],
        _streaming: true,
        _runId: run.id,
      }]);

      _activeAbort = streamRun(run.id, -1, {
        onEvent: (data) => handleStreamEvent(data, assistantId),
        onDone: () => handleStreamDone(assistantId),
        onError: (e) => handleStreamError(assistantId, e),
      });
    }
  } catch {}
}
