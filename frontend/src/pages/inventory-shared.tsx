import {useEffect, useId, useRef, useState, type ReactNode} from 'react';
import {Link, useSearchParams} from 'react-router-dom';
import Chart from 'chart.js/auto';
import {api} from '../api';

export type Id = number | string;
export type Values = Record<string, unknown>;
export type Errors = Record<string, string>;
export interface Result {ts: string; status: string; value: number | null; message?: string}
export interface Sensor {
  id: Id; device_id: Id; name: string; type: string; status: string; paused?: boolean;
  device_name?: string; group_name?: string; interval?: number; timeout?: number;
  down_after?: number; warning_threshold?: number | null; target?: string; unit?: string;
  params?: Values; last_result?: Result | null; last_value?: number | null; last_check?: string; message?: string;
}
export interface Device {
  id: Id; name: string; ip: string; device_type: string; status: string; paused?: boolean;
  mac?: string; vendor?: string; location?: string; notes?: string; group_id?: Id;
  group_name?: string; extra?: Values; sensors?: Sensor[]; last_check?: string;
  protocol?: string; port?: number; username?: string; driver?: string;
}
export interface Choice {id: Id; name: string; depth?: number}
export interface Group extends Choice {status?: string; children?: Group[]; devices?: Device[]}
export interface Pagination {page: number; pages: number; total: number; per_page: number}
export interface FieldSchema {
  label?: string; type?: string; default?: unknown; required?: boolean; min?: number;
  max?: number; step?: number | string; placeholder?: string; help?: string;
  choices?: (string | number | {value: string | number; label: string})[];
  options?: (string | number | {value: string | number; label: string})[];
}
export type Schema = Record<string, FieldSchema>;
export interface SensorType {label: string; params_schema?: Schema}
export interface DeviceType {label?: string; extra_fields?: Schema; default_sensors?: (string | {type: string})[]}
export interface Summary {uptime?: number | null; down_count?: number; down_seconds?: number; average_ms?: number | null}
export const statuses = ['DOWN', 'WARNING', 'UP', 'PAUSED', 'UNKNOWN'];
export const roleOf = (role: unknown) => String(role || '').toLowerCase();
export const messageOf = (error: unknown) => error instanceof Error ? error.message : 'Không tải được dữ liệu.';
export const errorsOf = (error: unknown): Errors => {
  if (typeof error === 'object' && error && 'errors' in error && typeof error.errors === 'object' && error.errors) return error.errors as Errors;
  return {};
};
export const text = (value: unknown): string => value == null || value === '' ? '–' : typeof value === 'object' ? JSON.stringify(value) : String(value);
export const time = (value?: string | null) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('vi-VN') : '–';
export const number = (value?: number | null) => value != null && Number.isFinite(value) ? value.toLocaleString('vi-VN', {maximumFractionDigits: 2}) : '–';
export const sensorValue = (sensor: Sensor) => {
  const value = sensor.last_value !== undefined ? sensor.last_value : sensor.last_result?.value;
  return value == null ? '–' : `${number(value)}${sensor.unit ? ` ${sensor.unit}` : ['ping', 'http'].includes(sensor.type) ? ' ms' : ''}`;
};

export function Status({status = 'UNKNOWN'}: {status?: string}) {
  const normalized = statuses.includes(status.toUpperCase()) ? status.toUpperCase() : 'UNKNOWN';
  return <span className={`nm-badge st-${normalized.toLowerCase()}`}>{normalized}</span>;
}
export function Panel({title, actions, children, flush = false}: {title: string; actions?: ReactNode; children: ReactNode; flush?: boolean}) {
  return <section className="nm-panel"><div className="nm-panel-head">{title}<div className="nm-panel-actions">{actions}</div></div><div className={`nm-panel-body${flush ? ' flush' : ''}`}>{children}</div></section>;
}
export function ErrorBox({error, retry}: {error: string; retry?: () => void}) {
  return <div className="nm-error-box" role="alert">{error} {retry && <button className="btn btn-secondary btn-sm" onClick={retry}>Thử lại</button>}</div>;
}
export function Loading() {return <div className="nm-loading" role="status"><span className="spinner-border" aria-hidden="true"/> Đang tải…</div>;}
export function Empty({children = 'Chưa có dữ liệu.'}: {children?: ReactNode}) {return <div className="nm-empty">{children}</div>;}
export function useRemote<T>(url: string, realtime = false) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    api.get<T>(url).then(result => {if (active) setData(result);}).catch(error => {if (active) setError(messageOf(error));}).finally(() => {if (active) setLoading(false);});
    return () => {active = false;};
  }, [url, version]);
  useEffect(() => {
    if (!realtime) return;
    const update = () => setVersion(value => value + 1);
    window.addEventListener('nm:status', update);
    return () => window.removeEventListener('nm:status', update);
  }, [realtime]);
  return {data, error, loading, reload: () => setVersion(value => value + 1)};
}
export function Pager({pagination}: {pagination?: Pagination}) {
  const [params, setParams] = useSearchParams();
  if (!pagination || pagination.total === 0) return null;
  const {page, pages, total, per_page} = pagination;
  const go = (next: number) => {const query = new URLSearchParams(params); query.set('page', String(next)); setParams(query);};
  return <nav className="nm-pager" aria-label="Phân trang"><button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => go(page - 1)}>‹ Trước</button><span>Trang {page} / {Math.max(1, pages)}</span><button className="btn btn-secondary btn-sm" disabled={page >= pages} onClick={() => go(page + 1)}>Sau ›</button><span className="info">Hiển thị {(page - 1) * per_page + 1}–{Math.min(page * per_page, total)} / {total}</span></nav>;
}
export function Row({label, name, error, required, children, hint}: {label: string; name: string; error?: string; required?: boolean; children: ReactNode; hint?: string}) {
  return <div className="nm-form-row"><label className="nm-form-label" htmlFor={name}>{label}{required && <span className="req">*</span>}</label><div className="nm-form-field">{children}{hint && <div className="nm-form-hint">{hint}</div>}{error && <div className="nm-form-error" id={`${name}-error`}>{error}</div>}</div></div>;
}
export function SchemaFields({schema = {}, values, errors = {}, prefix, onChange}: {schema?: Schema; values: Values; errors?: Errors; prefix: string; onChange: (name: string, value: unknown) => void}) {
  return <>{Object.entries(schema).map(([name, field]) => {
    const id = `${prefix}-${name}`;
    const value = values[name] ?? field.default ?? '';
    const error = errors[`${prefix}.${name}`] || errors[name];
    const props = {id, name: `${prefix}.${name}`, required: field.required, 'aria-invalid': !!error, 'aria-describedby': error ? `${id}-error` : undefined, className: `form-control${error ? ' is-invalid' : ''}`};
    const choices = field.options || field.choices;
    let input: ReactNode;
    if (field.type === 'boolean' || field.type === 'bool') input = <input {...props} className="form-check-input" type="checkbox" checked={value === true || value === 'true'} onChange={event => onChange(name, event.target.checked)}/>;
    else if (choices?.length) input = <select {...props} className={`form-select${error ? ' is-invalid' : ''}`} value={String(value)} onChange={event => onChange(name, event.target.value)}><option value="">Chọn…</option>{choices.map(choice => typeof choice === 'object' ? <option key={choice.value} value={choice.value}>{choice.label}</option> : <option key={choice} value={choice}>{choice}</option>)}</select>;
    else if (field.type === 'text') input = <textarea {...props} rows={3} value={String(value)} onChange={event => onChange(name, event.target.value)}/>;
    else {
      const numeric = ['number', 'int', 'integer', 'float'].includes(field.type || '');
      input = <input {...props} type={numeric ? 'number' : ['password', 'url', 'email'].includes(field.type || '') ? field.type : 'text'} min={field.min} max={field.max} step={field.step ?? (['float', 'number'].includes(field.type || '') ? 'any' : undefined)} placeholder={field.placeholder} value={String(value)} onChange={event => onChange(name, numeric && event.target.value !== '' ? Number(event.target.value) : event.target.value)}/>;
    }
    return <Row key={name} label={field.label || name} name={id} required={field.required} error={error} hint={field.help}>{input}</Row>;
  })}</>;
}
export function FormErrors({errors, error}: {errors: Errors; error: string}) {
  if (!error && !Object.keys(errors).length) return null;
  return <div className="nm-form-errors" role="alert">{error}<ul>{Object.entries(errors).map(([name, value]) => <li key={name}>{value}</li>)}</ul></div>;
}
export function SensorTiles({sensors = []}: {sensors?: Sensor[]}) {
  return <div className="nm-tiles">{sensors.map(sensor => <Link key={sensor.id} to={`/sensors/${sensor.id}`} className={`nm-tile st-${statuses.includes(sensor.status) ? sensor.status.toLowerCase() : 'unknown'}`} title={`${sensor.type} · ${sensor.status} · ${time(sensor.last_result?.ts)} · ${sensor.last_result?.message || ''}`} data-sensor-id={sensor.id}><span className="nm-tile-name">{sensor.name}</span><span className="nm-tile-value">{sensor.paused ? '⏸ PAUSED' : sensorValue(sensor)} <span className="visually-hidden">{sensor.status}</span></span></Link>)}</div>;
}

export function History({history = [], summary = {}, unit = 'ms', title = 'Độ trễ', latency = true}: {history?: Result[]; summary?: Summary; unit?: string; title?: string; latency?: boolean}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const tableId = useId();
  const chronological = history.filter(row => Number.isFinite(Date.parse(row.ts))).slice().sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
  useEffect(() => {
    if (!canvas.current || !latency || !chronological.length) return;
    const chart = new Chart(canvas.current, {
      type: 'line',
      data: {datasets: [{label: `${title} (${unit})`, data: chronological.map(row => ({x: Date.parse(row.ts), y: ['UP', 'WARNING'].includes(row.status.toUpperCase()) && row.value != null && Number.isFinite(row.value) ? row.value : null})), borderColor: '#1F6FB2', borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, pointHitRadius: 8, spanGaps: false, tension: 0}]},
      options: {responsive: true, maintainAspectRatio: false, animation: false, parsing: false, interaction: {mode: 'index', intersect: false}, plugins: {legend: {display: false}, tooltip: {callbacks: {title: items => items.length ? time(new Date(items[0].parsed.x).toISOString()) : '', label: item => `${title}: ${number(item.parsed.y)} ${unit}`}}}, scales: {x: {type: 'linear', title: {display: true, text: 'Thời gian'}, grid: {display: false}, ticks: {maxTicksLimit: 8, callback: value => new Date(Number(value)).toLocaleString('vi-VN', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'})}}, y: {beginAtZero: true, title: {display: true, text: `${title} (${unit})`}, grid: {color: '#EEF0F3'}}}},
      plugins: [{id: 'crosshair', afterDraw: chart => {
        const point = chart.getActiveElements()[0];
        if (!point) return;
        const {ctx, chartArea} = chart;
        ctx.save(); ctx.strokeStyle = '#6B7785'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(point.element.x, chartArea.top); ctx.lineTo(point.element.x, chartArea.bottom); ctx.stroke(); ctx.restore();
      }}],
    });
    return () => chart.destroy();
  }, [history, latency, title, unit]);
  return <><Panel title={latency ? `${title} theo thời gian` : 'Kết quả kiểm tra'}>{latency && chronological.length > 0 ? <><div style={{height: 240}}><canvas ref={canvas} role="img" aria-label={`${title} theo thời gian; khoảng DOWN, PAUSED và UNKNOWN không nối đường.`} aria-describedby={tableId}/></div><p className="nm-form-hint">Đường biểu diễn chỉ gồm kết quả UP/WARNING. Khoảng mất dữ liệu được để trống. <a href={`#${tableId}`}>Xem bảng kết quả</a>.</p></> : <Empty>{latency ? 'Chưa có dữ liệu trong khoảng đã chọn.' : 'Sensor này không đo độ trễ. Xem giá trị trong bảng kết quả.'}</Empty>}<div className="d-flex gap-4 flex-wrap" aria-label="Tóm tắt lịch sử"><span>Uptime <strong>{number(summary.uptime)} %</strong></span><span>DOWN <strong>{summary.down_count ?? '–'} lần</strong></span><span>Thời gian DOWN <strong>{summary.down_seconds == null ? '–' : `${number(summary.down_seconds)} giây`}</strong></span><span>Trung bình <strong>{number(summary.average_ms)} ms</strong></span></div></Panel><Panel title="Kết quả kiểm tra" flush><div className="table-responsive"><table className="nm-table" id={tableId}><thead><tr><th>Thời gian</th><th>Trạng thái</th><th>Giá trị{unit ? ` (${unit})` : ''}</th><th>Thông điệp</th></tr></thead><tbody>{history.map((row, index) => <tr key={`${row.ts}-${index}`}><td>{time(row.ts)}</td><td><Status status={row.status}/></td><td>{number(row.value)}</td><td className="wrap">{row.message || '–'}</td></tr>)}</tbody></table></div>{!history.length && <Empty/>}</Panel></>;
}
