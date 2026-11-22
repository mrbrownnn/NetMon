import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

// Exercise actual TypeScript transport without browser or extra test framework.
test('API loads CSRF, sends credentials, preserves validation failures and rotated token', async () => {
  const source = await readFile(new URL('./api.ts', import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  const { api, ApiError } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  const calls = [];
  let unauthorized = false;
  globalThis.window = { dispatchEvent(event) { unauthorized = event.type === 'nm:unauthorized'; } };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options });
    if (url === '/api/auth/session') return Response.json({ user: null, csrf_token: 'initial' });
    if (url === '/login') return Response.json({ user: { username: 'operator' }, csrf_token: 'rotated' });
    if (url === '/invalid') return Response.json({ message: 'Invalid', errors: { name: 'Required' } }, { status: 422 });
    if (url === '/private') return Response.json({ message: 'Login required' }, { status: 401 });
    return new Response(null, { status: 204 });
  };
  try {
    await api.post('/login', { username: 'operator', password: 'secret' });
    assert.equal(calls[0].url, '/api/auth/session');
    assert.equal(calls[1].headers.get('X-CSRFToken'), 'initial');
    assert.equal(calls[1].credentials, 'same-origin');
    assert.equal(calls[1].headers.get('Content-Type'), 'application/json');
    assert.deepEqual(JSON.parse(calls[1].body), { username: 'operator', password: 'secret' });
    assert.equal(await api.delete('/item'), null);
    assert.equal(calls[2].headers.get('X-CSRFToken'), 'rotated');
    await assert.rejects(api.post('/invalid', {}), error => error instanceof ApiError && error.status === 422 && error.errors.name === 'Required');
    await assert.rejects(api.get('/private'), error => error.status === 401);
    assert.equal(unauthorized, true);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
  }
});
