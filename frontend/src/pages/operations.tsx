import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';

export type FieldErrors = Record<string, string | string[]>;
export type Failure = { message: string; errors?: FieldErrors };
export type Group = { id: number; name: string; parent_id?: number | null };
export type Pagination = { page: number; pages: number; total: number; per_page: number };
export function descendants(groups: Group[], id: number): Set<number> {
  const excluded = new Set([id]);
  let changed = true;
  while (changed) { changed = false; for (const group of groups) if (group.parent_id != null && excluded.has(group.parent_id) && !excluded.has(group.id)) { excluded.add(group.id); changed = true; } }
  return excluded;
}
export type Sensor = { id: number; name: string; device_id: number; device_name?: string; status: string; last_value: number | null; unit?: string; message?: string; last_check?: string | null };
export type Alert = { id: number; level: string; state: string; created_at: string; device_id: number; device_name: string; sensor_id: number; sensor_name: string; old_status: string; new_status: string; duration_seconds?: number; ack_by?: string; note?: string };

export function failure(error: unknown): Failure {
  if (error && typeof error === 'object' && 'message' in error) return error as Failure;
  return { message: 'Không thể hoàn thành yêu cầu. Vui lòng thử lại.' };
}

export function useLoad<T>(url: string | null) {
  const [result, setResult] = useState<{ url: string; value: T } | null>(null);
  const data = result?.url === url ? result.value : null;
  const [error, setError] = useState<Failure | null>(null);
  const [loading, setLoading] = useState(Boolean(url));
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    let active = true;
    if (!url) { setLoading(false); setResult(null); return; }
    setLoading(true); setError(null);
    api.get<T>(url).then(value => { if (active) setResult({ url, value }); }).catch(reason => { if (active) setError(failure(reason)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [url, revision]);
  return { data, error, loading, reload };
}

export function useMutation() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Failure | null>(null);
  const [message, setMessage] = useState('');
  const lock = useRef(false);
  async function run(action: () => Promise<unknown>, success?: () => void | Promise<void>, successMessage = 'Đã lưu thay đổi.') {
    if (lock.current) return;
    lock.current = true; setPending(true); setError(null); setMessage('');
    try { await action(); await success?.(); setMessage(successMessage); }
    catch (reason) { setError(failure(reason)); }
    finally { lock.current = false; setPending(false); }
  }
  return { pending, error, message, run, clear: () => { setError(null); setMessage(''); } };
}

export const roleName = (role: unknown) => String(typeof role === 'object' && role !== null && 'value' in role ? role.value : role ?? '').toLowerCase();
export function timestamp(value?: string | null) {
  if (!value) return '–';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('vi-VN');
}
export function number(value: number | null | undefined, suffix = '') { return value == null ? '–' : `${value.toLocaleString('vi-VN', { maximumFractionDigits: 2 })}${suffix}`; }
export function duration(value?: number | null) {
  if (value == null) return '–';
  const seconds = Math.max(0, Math.floor(value));
  return [seconds >= 86400 && `${Math.floor(seconds / 86400)} ngày`, seconds >= 3600 && `${Math.floor(seconds % 86400 / 3600)} giờ`, seconds >= 60 && `${Math.floor(seconds % 3600 / 60)} phút`, `${seconds % 60} giây`].filter(Boolean).join(' ');
}
export function Status({ value }: { value?: string }) {
  const status = String(value ?? 'UNKNOWN').toUpperCase();
  const names: Record<string, string> = { UP: 'up', WARNING: 'warning', DOWN: 'down', PAUSED: 'paused', UNKNOWN: 'unknown', CRITICAL: 'down', INFO: 'paused', 'DOWN-ACK': 'down-ack' };
  return <span className={`nm-badge st-${names[status] ?? 'unknown'}`}>{status}</span>;
}
export function Panel({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return <section className="nm-panel"><header className="nm-panel-head">{title}<div className="nm-panel-actions">{actions}</div></header><div className="nm-panel-body">{children}</div></section>;
}
export function Errors({ error }: { error: Failure | null | undefined }) {
  return error ? <div className="nm-form-errors" role="alert"><div>{error.message}</div>{error.errors && <ul>{Object.entries(error.errors).map(([key, value]) => <li key={key}>{Array.isArray(value) ? value.join(', ') : value}</li>)}</ul>}</div> : null;
}
export function Notice({ mutation }: { mutation: ReturnType<typeof useMutation> }) {
  return <><Errors error={mutation.error} />{mutation.message && <p role="status">{mutation.message}</p>}</>;
}
export function Field({ label, name, error, children, hint }: { label: string; name: string; error?: FieldErrors; children: ReactNode; hint?: string }) {
  const text = error?.[name];
  return <div className={`nm-form-row${text ? ' has-error' : ''}`}><label className="nm-form-label" htmlFor={name}>{label}</label><div className="nm-form-field">{children}{hint && <div className="nm-form-hint">{hint}</div>}{text && <div id={`${name}-error`} className="nm-form-error">{Array.isArray(text) ? text.join(', ') : text}</div>}</div></div>;
}
export function LoadState({ resource }: { resource: { data: unknown; loading: boolean; error: Failure | null; reload: () => void } }) {
  return <><Errors error={resource.error} />{resource.error && <button type="button" className="btn btn-secondary mb-2" onClick={resource.reload}>Thử lại</button>}{resource.loading && !resource.data && <p className="nm-loading" role="status">Đang tải…</p>}</>;
}
export function Empty({ columns, text = 'Không có dữ liệu.' }: { columns: number; text?: string }) { return <tr><td colSpan={columns} className="nm-empty">{text}</td></tr>; }
export function Pager({ pagination }: { pagination?: Pagination }) {
  const [params] = useSearchParams();
  if (!pagination || pagination.pages <= 1) return pagination ? <div className="nm-pager">Tổng {pagination.total} bản ghi</div> : null;
  const href = (page: number) => { const next = new URLSearchParams(params); next.set('page', String(page)); return `?${next}`; };
  return <nav className="nm-pager" aria-label="Phân trang">{pagination.page > 1 && <Link to={href(pagination.page - 1)}>Trước</Link>}<span>Trang {pagination.page} / {pagination.pages}</span>{pagination.page < pagination.pages && <Link to={href(pagination.page + 1)}>Sau</Link>}<span className="info">Tổng {pagination.total} bản ghi</span></nav>;
}
export function useFilters() {
  const [params, setParams] = useSearchParams();
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = new URLSearchParams();
    new FormData(event.currentTarget).forEach((value, key) => { if (String(value)) next.set(key, String(value)); });
    setParams(next);
  }
  return { params, submit };
}
export function Dates({ params }: { params: URLSearchParams }) { return <><label>Từ <input className="form-control" aria-label="Từ ngày" type="date" name="start" defaultValue={params.get('start') ?? ''} /></label><label>Đến <input className="form-control" aria-label="Đến ngày" type="date" name="end" defaultValue={params.get('end') ?? ''} /></label></>; }
