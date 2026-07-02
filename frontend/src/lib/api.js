const API_BASE = '';

async function request(method, path, body) {
  const opts = {
    method,
    credentials: 'include',
    headers: {},
  };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(`${API_BASE}${path}`, opts);
  if (r.status === 401) {
    const err = new Error('Session expired');
    err.status = 401;
    throw err;
  }
  let data = null;
  try { data = await r.json(); } catch {}
  if (!r.ok) {
    const msg = (data && (data.detail || data.error || data.message)) || `HTTP ${r.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

export const api = {
  me:            () => request('GET', '/api/me'),
  login:         (username, password) => request('POST', '/api/login', { username, password }),
  logout:        () => request('POST', '/api/logout'),
  messages:      () => request('GET', '/api/messages'),
  clearMessages: () => request('DELETE', '/api/messages'),
  settings:      () => request('GET', '/api/settings'),
  saveSettings:  (patch) => request('POST', '/api/settings', patch),
  saveCreds:     (patch) => request('POST', '/api/credentials', patch),
  resetSandbox:  () => request('POST', '/api/sandbox/reset'),
  createSandbox: () => request('POST', '/api/sandbox/create'),
  deleteSandbox: () => request('POST', '/api/sandbox/delete'),
  startMessage:  (content) => request('POST', '/api/message', { content }),
  activeRun:     () => request('GET', '/api/runs/active'),
  testVps:       (target) => request('POST', `/api/vps/test${target ? '?target=' + target : ''}`),
};

/**
 * Connect to an SSE stream for a run. Returns an unsubscribe function.
 * @param {string} runId
 * @param {number} afterSeq
 * @param {function} onEvent - called with parsed event data
 * @param {function} onDone - called when stream ends
 * @param {function} onError - called on error
 * @returns {function} abort function
 */
export function streamRun(runId, afterSeq, { onEvent, onDone, onError }) {
  const controller = new AbortController();

  (async () => {
    try {
      const url = `/api/run/${encodeURIComponent(runId)}/stream?after=${afterSeq}`;
      const r = await fetch(url, {
        method: 'GET',
        credentials: 'include',
        signal: controller.signal,
        headers: { Accept: 'text/event-stream' },
      });

      if (r.status === 401) {
        const err = new Error('Session expired');
        err.status = 401;
        throw err;
      }
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try { const j = await r.json(); detail = j.detail || detail; } catch {}
        throw new Error(detail);
      }

      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          for (const line of raw.split('\n')) {
            if (!line.startsWith('data:')) continue;
            const data = line.slice(5).trim();
            if (!data) continue;
            try { onEvent(JSON.parse(data)); } catch {}
          }
        }
      }
      onDone?.();
    } catch (e) {
      if (e.name === 'AbortError') return;
      onError?.(e);
    }
  })();

  return () => controller.abort();
}
