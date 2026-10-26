let sessionToken = '';
let stateCache: unknown;
let stateEtag = '';
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const r = await fetch('/api' + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Outreach-Token': sessionToken,
      ...(path === '/state' && stateEtag ? { 'If-None-Match': stateEtag } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 304 && path === '/state' && stateCache) return stateCache as T;
  // Unhandled server errors are plain text; never surface a JSON parse error instead.
  const raw = await r.text();
  let data: any;
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    throw Object.assign(
      new Error(
        r.ok
          ? 'The app returned an unexpected response. Reload and retry.'
          : `Request failed (HTTP ${r.status}). Check the app logs and retry.`,
      ),
      { status: r.status },
    );
  }
  if (path === '/bootstrap') {
    sessionToken = data.token;
    stateCache = undefined;
    stateEtag = '';
  }
  if (!r.ok) throw Object.assign(new Error(data.detail || 'Request failed'), { status: r.status });
  if (path === '/state' && r.ok) {
    stateCache = data;
    stateEtag = r.headers.get('ETag') || '';
  }
  return data;
}
