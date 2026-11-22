import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import { Empty, Field, LoadState, Notice, Panel, descendants, roleName, timestamp, useLoad, useMutation, type FieldErrors, type Group } from './operations';

type User = { id: number; username: string; role: string; locked: boolean; last_login?: string };
type SettingsData = { users: User[]; groups: Group[]; values: Record<string, string | number>; errors?: FieldErrors; system: { version: string; scheduler_running: boolean; sensor_count: number; worker_count: number } };
function PasswordReset({ user }: { user: User }) {
  const mutation = useMutation();
  const [password, setPassword] = useState('');
  return <details><summary>Đặt lại mật khẩu</summary><form className="p-2" onSubmit={event => { event.preventDefault(); void mutation.run(() => api.post(`/api/settings/users/${user.id}/password`, { password }), () => setPassword(''), 'Đã đặt lại mật khẩu.'); }}><Notice mutation={mutation} /><label htmlFor={`reset-${user.id}`}>Mật khẩu mới cho {user.username}</label><input id={`reset-${user.id}`} className="form-control" type="password" autoComplete="new-password" required value={password} onChange={event => setPassword(event.target.value)} /><button className="btn btn-secondary mt-1" type="submit" disabled={mutation.pending}>Đặt lại mật khẩu</button></form></details>;
}
function UserEditor({ user, done }: { user?: User; done: () => void }) {
  const mutation = useMutation();
  const [values, setValues] = useState({ username: user?.username ?? '', role: roleName(user?.role) || 'viewer', password: '' });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void mutation.run(() => user ? api.put(`/api/settings/users/${user.id}`, { role: values.role }) : api.post('/api/settings/users', values), done);
  }
  return <Panel title={user ? `Sửa tài khoản ${user.username}` : 'Thêm tài khoản'}><form onSubmit={submit}><Notice mutation={mutation} /><Field label="Tên đăng nhập *" name="username" error={mutation.error?.errors} hint={user ? 'Tên đăng nhập không thể đổi.' : undefined}><input id="username" className="form-control" required readOnly={Boolean(user)} autoComplete="off" value={values.username} onChange={event => setValues({ ...values, username: event.target.value })} /></Field><Field label="Vai trò *" name="role" error={mutation.error?.errors}><select id="role" className="form-select" value={values.role} onChange={event => setValues({ ...values, role: event.target.value })}><option value="viewer">Viewer — chỉ xem</option><option value="operator">Operator — vận hành</option><option value="admin">Admin — quản trị</option></select></Field>{!user && <Field label="Mật khẩu *" name="password" error={mutation.error?.errors}><input id="password" type="password" autoComplete="new-password" required className="form-control" value={values.password} onChange={event => setValues({ ...values, password: event.target.value })} /></Field>}<div className="nm-form-actions"><button className="btn btn-primary" disabled={mutation.pending} type="submit">Lưu</button><button className="btn btn-link" type="button" onClick={done}>Hủy</button></div></form></Panel>;
}
function Users({ users, reload, selfId }: { users: User[]; reload: () => void; selfId?: number }) {
  const [editor, setEditor] = useState<User | 'new' | null>(null);
  const mutation = useMutation();
  return <>{editor && <UserEditor key={editor === 'new' ? 'new' : editor.id} user={editor === 'new' ? undefined : editor} done={() => { setEditor(null); reload(); }} />}<Panel title="Tài khoản" actions={<button className="btn btn-primary" type="button" onClick={() => setEditor('new')}>Thêm tài khoản</button>}><Notice mutation={mutation} /><table className="nm-table"><thead><tr><th>Tên</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập cuối</th><th>Thao tác</th></tr></thead><tbody>{users.map(user => <tr key={user.id}><td>{user.username}</td><td>{roleName(user.role)}</td><td>{user.locked ? 'Đã khóa' : 'Hoạt động'}</td><td>{timestamp(user.last_login)}</td><td><div className="d-flex gap-2 align-items-start"><button className="btn btn-link" type="button" onClick={() => setEditor(user)}>Sửa</button>{user.id !== selfId && <button type="button" className="btn btn-secondary" disabled={mutation.pending} onClick={() => { if (user.locked || window.confirm(`Khóa tài khoản ${user.username}? Người dùng sẽ không thể đăng nhập.`)) void mutation.run(() => api.post(`/api/settings/users/${user.id}/${user.locked ? 'unlock' : 'lock'}`, {}), reload); }}>{user.locked ? 'Mở khóa' : 'Khóa'}</button>}<PasswordReset user={user} /></div></td></tr>)}{!users.length && <Empty columns={5} text="Chưa có tài khoản." />}</tbody></table></Panel></>;
}
function GroupEditor({ group, groups, done }: { group?: Group; groups: Group[]; done: () => void }) {
  const mutation = useMutation();
  const [name, setName] = useState(group?.name ?? '');
  const [parent, setParent] = useState(group?.parent_id == null ? '' : String(group.parent_id));
  const excluded = group ? descendants(groups, group.id) : new Set<number>();
  return <Panel title={group ? `Sửa nhóm ${group.name}` : 'Thêm nhóm'}><form onSubmit={event => { event.preventDefault(); const values = { name, parent_id: parent ? Number(parent) : null }; void mutation.run(() => group ? api.put(`/api/settings/groups/${group.id}`, values) : api.post('/api/settings/groups', values), done); }}><Notice mutation={mutation} /><Field label="Tên nhóm *" name="name" error={mutation.error?.errors}><input id="name" required className="form-control" value={name} onChange={event => setName(event.target.value)} /></Field><Field label="Nhóm cha" name="parent_id" error={mutation.error?.errors}><select id="parent_id" className="form-select" value={parent} onChange={event => setParent(event.target.value)}><option value="">Không có — nhóm gốc</option>{groups.filter(item => !excluded.has(item.id)).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><div className="nm-form-actions"><button className="btn btn-primary" disabled={mutation.pending} type="submit">Lưu</button><button className="btn btn-link" type="button" onClick={done}>Hủy</button></div></form></Panel>;
}
function Groups({ groups, reload }: { groups: Group[]; reload: () => void }) {
  const [editor, setEditor] = useState<Group | 'new' | null>(null);
  const mutation = useMutation();
  return <>{editor && <GroupEditor key={editor === 'new' ? 'new' : editor.id} group={editor === 'new' ? undefined : editor} groups={groups} done={() => { setEditor(null); reload(); }} />}<Panel title="Nhóm" actions={<button className="btn btn-primary" type="button" onClick={() => setEditor('new')}>Thêm nhóm</button>}><Notice mutation={mutation} /><table className="nm-table"><thead><tr><th>Tên nhóm</th><th>Nhóm cha</th><th>Thao tác</th></tr></thead><tbody>{groups.map(group => <tr key={group.id}><td>{group.name}</td><td>{groups.find(parent => parent.id === group.parent_id)?.name ?? '–'}</td><td><button className="btn btn-link" onClick={() => setEditor(group)}>Sửa / chuyển nhóm</button><button className="btn btn-danger" disabled={mutation.pending} onClick={() => { if (window.confirm(`Xóa nhóm ${group.name}? Không thể hoàn tác. Nhóm còn thiết bị hoặc nhóm con sẽ bị từ chối.`)) void mutation.run(() => api.delete(`/api/settings/groups/${group.id}`), reload, 'Đã xóa nhóm.'); }}>Xóa</button></td></tr>)}{!groups.length && <Empty columns={3} text="Chưa có nhóm." />}</tbody></table></Panel></>;
}
function Monitoring({ values, errors }: { values: SettingsData['values']; errors?: FieldErrors }) {
  const mutation = useMutation();
  const fields = [{ name: 'default_interval', label: 'Chu kỳ mặc định (giây)', min: 10, max: 3600 }, { name: 'down_after', label: 'Số lần lỗi trước DOWN', min: 1, max: 100 }, { name: 'history_days', label: 'Số ngày giữ lịch sử', min: 1, max: 3650 }];
  return <Panel title="Thiết lập giám sát"><form onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); void mutation.run(() => api.put('/api/settings/monitoring', { default_interval: Number(form.get('default_interval')), down_after: Number(form.get('down_after')), history_days: Number(form.get('history_days')), backup_time: String(form.get('backup_time')) })); }}><Notice mutation={mutation} />{fields.map(field => <Field key={field.name} name={field.name} label={`${field.label} *`} error={mutation.error?.errors ?? errors}><input id={field.name} name={field.name} className="form-control" type="number" min={field.min} max={field.max} required defaultValue={values[field.name] ?? ''} /></Field>)}<Field label="Giờ backup hằng ngày *" name="backup_time" error={mutation.error?.errors ?? errors}><input id="backup_time" className="form-control" name="backup_time" type="time" required defaultValue={values.backup_time ?? ''} /></Field><div className="nm-form-actions"><button className="btn btn-primary" disabled={mutation.pending} type="submit">Lưu</button></div></form></Panel>;
}
function System({ system, reload }: { system: SettingsData['system']; reload: () => void }) {
  const mutation = useMutation();
  return <Panel title="Hệ thống"><Notice mutation={mutation} /><table className="nm-table"><tbody><tr><th>Phiên bản</th><td>{system.version ?? '–'}</td></tr><tr><th>Scheduler</th><td>{system.scheduler_running == null ? '–' : system.scheduler_running ? 'Đang chạy' : 'Đã dừng'}</td></tr><tr><th>Số sensor</th><td>{system.sensor_count ?? '–'}</td></tr><tr><th>Số luồng</th><td>{system.worker_count ?? '–'}</td></tr></tbody></table><button className="btn btn-secondary mt-3" disabled={mutation.pending} onClick={() => { if (window.confirm('Khởi động lại scheduler? Các lần kiểm tra có thể tạm gián đoạn.')) void mutation.run(() => api.post('/api/settings/scheduler/restart', {}), reload, 'Đã khởi động lại scheduler.'); }}>Khởi động lại scheduler</button></Panel>;
}
export default function Settings() {
  const { user } = useAuth();
  const admin = roleName(user?.role) === 'admin';
  const [params] = useSearchParams();
  const tab = ['users', 'groups', 'monitoring', 'system'].includes(params.get('tab') ?? '') ? params.get('tab')! : 'users';
  const resource = useLoad<SettingsData>(admin ? `/api/settings?tab=${tab}` : null);
  if (!admin) return <div className="nm-error-box" role="alert">Chỉ quản trị viên được thay đổi cài đặt.</div>;
  const data = resource.data;
  return <><div className="nm-page-head"><h1>Cài đặt</h1></div><div className="d-flex gap-3"><nav className="nav flex-column" aria-label="Cài đặt" style={{ minWidth: 160 }}>{[['users', 'Tài khoản'], ['groups', 'Nhóm'], ['monitoring', 'Giám sát'], ['system', 'Hệ thống']].map(([key, label]) => <Link key={key} className={`nav-link${tab === key ? ' active fw-bold' : ''}`} aria-current={tab === key ? 'page' : undefined} to={`/settings?tab=${key}`}>{label}</Link>)}</nav><div className="flex-grow-1" style={{ minWidth: 0 }}><LoadState resource={resource} />{data && <div key={tab}>{tab === 'users' && <Users users={data.users} reload={resource.reload} selfId={user?.id} />}{tab === 'groups' && <Groups groups={data.groups} reload={resource.reload} />}{tab === 'monitoring' && <Monitoring values={data.values} errors={data.errors} />}{tab === 'system' && <System system={data.system} reload={resource.reload} />}</div>}</div></div></>;
}
