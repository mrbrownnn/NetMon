import {useState} from 'react';
import {Link, useNavigate, useParams, useSearchParams} from 'react-router-dom';
import {api} from '../api';
import {useAuth} from '../auth';
import {ErrorBox, History, Loading, Panel, Status, messageOf, roleOf, sensorValue, text, time, useRemote, type Device, type Result, type Sensor, type Summary} from './inventory-shared';

interface SensorDetailData {sensor: Sensor; device: Device; history: Result[]; history_summary: Summary}
export default function SensorDetail() {
  const {id} = useParams(); const [params, setParams] = useSearchParams(); const navigate = useNavigate(); const {user} = useAuth();
  const {data, loading, error, reload} = useRemote<SensorDetailData>(`/api/sensors/${id}?${params}`, true);
  const [busy, setBusy] = useState(false); const [actionError, setActionError] = useState('');
  const admin = roleOf(user?.role) === 'admin';
  async function action(action: 'check' | 'pause' | 'resume' | 'delete') {
    if (action === 'delete' && !window.confirm('Xóa vĩnh viễn sensor cùng lịch sử kiểm tra?')) return;
    setBusy(true); setActionError('');
    try {if (action === 'delete') {await api.delete(`/api/sensors/${id}`); navigate('/sensors');} else {await api.post(`/api/sensors/${id}/${action}`, {}); reload();}}
    catch (error) {setActionError(messageOf(error));} finally {setBusy(false);}
  }
  if (loading && !data) return <Loading/>;
  if (error || !data) return <ErrorBox error={error || 'Không tìm thấy sensor.'} retry={reload}/>;
  const {sensor, device} = data;
  const latency = sensor.unit === 'ms' || ['ping', 'http'].includes(sensor.type);
  function range(value: string) {const next = new URLSearchParams(params); next.set('range', value); setParams(next);}
  return <><div className="nm-page-head"><h1>{sensor.name}</h1><Status status={sensor.status}/><div className="nm-page-actions">{admin && <><button className="btn btn-secondary" disabled={busy} onClick={() => action('check')}>Kiểm tra ngay</button><button className="btn btn-secondary" disabled={busy} onClick={() => action(sensor.paused ? 'resume' : 'pause')}>{sensor.paused ? 'Tiếp tục' : 'Tạm dừng'}</button><Link className="btn btn-primary" to={`/sensors/${id}/edit`}>Sửa</Link><button className="btn btn-danger" disabled={busy} onClick={() => action('delete')}>Xóa</button></>}</div></div><p className="muted"><Link to={`/devices/${device.id}`}>{device.name}</Link> · <span className="ip">{device.ip}</span> · {sensor.type} · Lần kiểm tra cuối {time(sensor.last_check || sensor.last_result?.ts)}</p>{actionError && <ErrorBox error={actionError}/>}<Panel title="Lịch sử kiểm tra"><div className="d-flex gap-2 align-items-center flex-wrap">{[['24h', '24 giờ'], ['7d', '7 ngày'], ['30d', '30 ngày']].map(([value, label]) => <button className={`btn btn-secondary${(params.get('range') || '24h') === value ? ' active' : ''}`} key={value} aria-pressed={(params.get('range') || '24h') === value} onClick={() => range(value)}>{label}</button>)}<form className="d-flex gap-2 align-items-center" onSubmit={event => {event.preventDefault(); const form = new FormData(event.currentTarget); const from = String(form.get('from') || ''); const to = String(form.get('to') || ''); if (!from || !to || Date.parse(from) > Date.parse(to)) {setActionError('Khoảng thời gian không hợp lệ.'); return;} const next = new URLSearchParams(params); next.set('range', 'custom'); next.set('from', from); next.set('to', to); setActionError(''); setParams(next);}}><label>Từ <input type="datetime-local" name="from" className="form-control" required defaultValue={params.get('from') || ''}/></label><label>Đến <input type="datetime-local" name="to" className="form-control" required defaultValue={params.get('to') || ''}/></label><button className="btn btn-secondary">Áp dụng</button></form>{loading && <span role="status">Đang cập nhật…</span>}</div></Panel><History history={data.history || []} summary={data.history_summary} latency={latency} unit={sensor.unit || (latency ? 'ms' : '')}/><Panel title="Cài đặt sensor" flush><table className="nm-table"><tbody>{[['Loại', sensor.type], ['Giá trị cuối', sensorValue(sensor)], ['Thiết bị', device.name], ['Đích kiểm tra', sensor.target || device.ip], ['Chu kỳ (giây)', sensor.interval], ['Timeout (giây)', sensor.timeout], ['Số lần lỗi trước DOWN', sensor.down_after], ['Ngưỡng WARNING', sensor.warning_threshold], ...Object.entries(sensor.params || {}).map(([name, value]) => [name, /community|password|secret|token/i.test(name) ? '••••••' : value])].map(([label, value]) => <tr key={String(label)}><th>{String(label)}</th><td className="wrap">{text(value)}</td></tr>)}</tbody></table></Panel></>;
}
