import type { Session } from './types';

export class ApiError extends Error {
  constructor(message: string, public status: number, public errors: Record<string, string> = {}) {
    super(message);
    this.name = 'ApiError';
  }
}

let csrfToken = '';
let sessionRequest: Promise<Session> | null = null;

export async function loadSession(): Promise<Session> {
  if (!sessionRequest) {
    sessionRequest = request<Session>('GET', '/api/auth/session').then(session => {
      csrfToken = session.csrf_token;
      return session;
    }).finally(() => { sessionRequest = null; });
  }
  return sessionRequest;
}

async function request<T>(method: string, url: string, body?: unknown, options?: RequestInit): Promise<T> {
  const mutation = !['GET', 'HEAD'].includes(method);
  if (mutation && !csrfToken) await loadSession();
  const headers = new Headers(options?.headers);
  headers.set('Accept', 'application/json');
  if (body !== undefined) headers.set('Content-Type', 'application/json');
  if (mutation) headers.set('X-CSRFToken', csrfToken);
  const response = await fetch(url, {
    ...options, method, credentials: 'same-origin', headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; }
  catch { throw new ApiError('Phản hồi máy chủ không hợp lệ.', response.status); }
  if (!response.ok) {
    const error = data && typeof data === 'object' ? data as { message?: unknown; errors?: Record<string, string> } : {};
    if (response.status === 401) window.dispatchEvent(new Event('nm:unauthorized'));
    throw new ApiError(typeof error.message === 'string' ? error.message : `HTTP ${response.status}`, response.status, error.errors);
  }
  if (data && typeof data === 'object' && 'csrf_token' in data && typeof data.csrf_token === 'string') {
    csrfToken = data.csrf_token;
  }
  return data as T;
}

export const api = {
  get: <T>(url: string, options?: RequestInit) => request<T>('GET', url, undefined, options),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body),
  put: <T>(url: string, body?: unknown) => request<T>('PUT', url, body),
  patch: <T>(url: string, body?: unknown) => request<T>('PATCH', url, body),
  delete: <T>(url: string) => request<T>('DELETE', url),
};
