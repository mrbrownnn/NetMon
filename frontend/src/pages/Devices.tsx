import {useState, type FormEvent} from 'react';
import {Link, useSearchParams} from 'react-router-dom';
import {api} from '../api';
import {useAuth} from '../auth';
import {Empty, ErrorBox, Loading, Pager, Panel, SensorTiles, Status, messageOf, roleOf, statuses, time, useRemote, type Choice, type Device, type Group, type Pagination} from './inventory-shared';

interface DeviceList {devices: Device[]; groups: Choice[]; tree: Group[]; pagination: Pagination; device_types?: Record<string, {label?: string}>}
export default function Devices() {
  const {user} = useAuth();
  const admin = roleOf(user?.role) === 'admin';
  const [params, setParams] = useSearchParams();
  const {data, loading, error, reload} = useRemote<DeviceList>(`/api/devices?${params}`);
  const [view, setView] = useState<'tree' | 'table'>('tree');
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const query = new URLSearchParams();
    new FormData(event.currentTarget).forEach((value, key) => {if (String(value)) query.set(key, String(value));});
    setSelected([]); setParams(query);
  }
  async function mutate(ids: string[], action: 'pause' | 'resume' | 'delete') {
    if (!ids.length || !window.confirm(`${action === 'delete' ? 'Xóa vĩnh viễn thiết bị và sensor liên quan' : action === 'pause' ? 'Tạm dừng giám sát thiết bị' : 'Tiếp tục giám sát thiết bị'} (${ids.length})?`)) return;
    setBusy(true); setActionError(''); let completed = 0;
    try {for (const id of ids) {if (action === 'delete') await api.delete(`/api/devices/${id}`); else await api.post(`/api/devices/${id}/${action}`, {}); completed++;} setSelected([]);}
    catch (error) {setActionError(`${messageOf(error)} Đã xử lý ${completed}/${ids.length} thiết bị. Các thay đổi thành công được giữ lại.`);}
    finally {setBusy(false); reload();}
  }
  const controls = (device: Device) => admin && <div className="d-flex gap-1"><Link className="btn btn-link btn-sm" to={`/devices/${device.id}/edit`}>Sửa</Link><Link className="btn btn-link btn-sm" to={`/sensors/new?device_id=${device.id}`}>Thêm sensor</Link><button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => mutate([String(device.id)], device.paused ? 'resume' : 'pause')}>{device.paused ? 'Tiếp tục' : 'Tạm dừng'}</button><button className="btn btn-danger btn-sm" disabled={busy} onClick={() => mutate([String(device.id)], 'delete')}>Xóa</button></div>;
  const deviceNode = (device: Device) => <li key={`device-${device.id}`} data-device-id={device.id}><div className="nm-tree-row"><Status status={device.status}/><Link to={`/devices/${device.id}`}>{device.name}</Link><span className="ip">{device.ip}</span><span className="muted">{device.vendor || device.device_type}</span><div className="ms-auto">{controls(device)}</div></div><div className="px-4 pb-2"><SensorTiles sensors={device.sensors}/></div></li>;
  function groupNode(group: Group) {
    return <li key={`group-${group.id}`} data-group-id={group.id}><details open><summary className="nm-tree-row"><Status status={group.status}/><strong>{group.name}</strong><span className="nm-tree-summary">{group.devices?.length || 0} thiết bị trực tiếp</span></summary><ul className="nm-tree">{(group.children || []).map(groupNode)}{(group.devices || []).map(deviceNode)}</ul></details></li>;
  }
  const devices = data?.devices || [];
  const treeDeviceIds = new Set<string>();
  function collect(groups: Group[]) {for (const group of groups) {for (const device of group.devices || []) treeDeviceIds.add(String(device.id)); collect(group.children || []);}}
  collect(data?.tree || []);
  return <><div className="nm-page-head"><h1>Thiết bị</h1><div className="nm-page-actions"><div className="btn-group" aria-label="Chế độ xem"><button className={`btn btn-secondary${view === 'tree' ? ' active' : ''}`} aria-pressed={view === 'tree'} onClick={() => setView('tree')}>Cây</button><button className={`btn btn-secondary${view === 'table' ? ' active' : ''}`} aria-pressed={view === 'table'} onClick={() => setView('table')}>Bảng</button></div>{admin && <Link className="btn btn-primary" to="/devices/new">+ Thêm thiết bị</Link>}</div></div>{actionError && <ErrorBox error={actionError}/>}<Panel title="Danh sách thiết bị" flush><form className="nm-toolbar" onSubmit={filter} key={params.toString()}><input className="form-control" style={{width: 240}} name="q" aria-label="Lọc tên hoặc IP" placeholder="Lọc tên / IP…" defaultValue={params.get('q') || ''}/><select className="form-select w-auto" name="status" aria-label="Trạng thái" defaultValue={params.get('status') || ''}><option value="">Tất cả trạng thái</option>{statuses.map(status => <option key={status}>{status}</option>)}</select><select className="form-select w-auto" name="type" aria-label="Loại thiết bị" defaultValue={params.get('type') || ''}><option value="">Tất cả loại</option>{Object.entries(data?.device_types || {router: {label: 'Router'}, switch: {label: 'Switch'}, server: {label: 'Server'}, pc: {label: 'PC'}, printer: {label: 'Printer'}}).map(([key, type]) => <option value={key} key={key}>{type.label || key}</option>)}</select><select className="form-select w-auto" name="group_id" aria-label="Nhóm" defaultValue={params.get('group_id') || ''}><option value="">Tất cả nhóm</option>{data?.groups?.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select><button className="btn btn-secondary">Lọc</button><Link className="btn btn-link" to="/devices">Xóa bộ lọc</Link></form>{admin && view === 'table' && selected.length > 0 && <div className="nm-toolbar"><strong>Đã chọn {selected.length}</strong>{(['pause', 'resume', 'delete'] as const).map(action => <button key={action} disabled={busy} className={`btn btn-${action === 'delete' ? 'danger' : 'secondary'}`} onClick={() => mutate(selected, action)}>{action === 'delete' ? 'Xóa' : action === 'pause' ? 'Tạm dừng' : 'Tiếp tục'}</button>)}</div>}{loading ? <Loading/> : error ? <ErrorBox error={error} retry={reload}/> : !devices.length && !data?.tree?.length ? <Empty>Chưa có thiết bị phù hợp. {admin && <Link to="/devices/new">Thêm thiết bị</Link>}</Empty> : view === 'tree' ? <ul className="nm-tree">{(data?.tree || []).map(groupNode)}{devices.filter(device => !treeDeviceIds.has(String(device.id))).map(deviceNode)}</ul> : <div className="table-responsive"><table className="nm-table"><thead><tr>{admin && <th><input type="checkbox" aria-label="Chọn tất cả thiết bị trên trang" checked={devices.length > 0 && devices.every(device => selected.includes(String(device.id)))} onChange={event => setSelected(event.target.checked ? devices.map(device => String(device.id)) : [])}/></th>}<th>Trạng thái</th><th>Tên</th><th>IP</th><th>Loại</th><th>Nhóm</th><th>Hãng</th><th>Sensor</th><th>Lần kiểm tra cuối</th>{admin && <th>Thao tác</th>}</tr></thead><tbody>{devices.map(device => <tr key={device.id} data-device-id={device.id}>{admin && <td><input type="checkbox" aria-label={`Chọn ${device.name}`} checked={selected.includes(String(device.id))} onChange={event => setSelected(current => event.target.checked ? [...current, String(device.id)] : current.filter(id => id !== String(device.id)))}/></td>}<td><Status status={device.status}/></td><td><Link to={`/devices/${device.id}`}>{device.name}</Link></td><td className="ip">{device.ip}</td><td>{device.device_type}</td><td>{device.group_name || '–'}</td><td>{device.vendor || '–'}</td><td><SensorTiles sensors={device.sensors}/></td><td>{time(device.last_check)}</td>{admin && <td>{controls(device)}</td>}</tr>)}</tbody></table></div>}<Pager pagination={data?.pagination}/></Panel></>;
}
