import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import { Empty, Errors, Field, LoadState, Notice, Panel, failure, roleName, useLoad, useMutation, type Failure, type Group } from './operations';

type Result = { ip: string; hostname: string; ports: number[]; type: string; exists: boolean };
type Job = { id: string | number; status: 'running' | 'completed' | 'stopped' | 'failed'; completed: number; total: number; results: Result[] };
export default function Discovery() {
  const { user } = useAuth();
  const admin = roleName(user?.role) === 'admin';
  const [params, setParams] = useSearchParams();
  const groups = useLoad<{ groups: Group[] }>(admin ? '/api/groups' : null);
  const [job, setJob] = useState<Job | null>(null);
  const [pollError, setPollError] = useState<Failure | null>(null);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [groupId, setGroupId] = useState('');
  const start = useMutation();
  const stop = useMutation();
  const imports = useMutation();
  const jobId = params.get('job');
  useEffect(() => {
    if (!admin || !jobId) { setJob(null); return; }
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setJob(null); setPollError(null); setSelected([]);
    async function poll() {
      try {
        const result = await api.get<Job>(`/api/discovery/${encodeURIComponent(jobId!)}`);
        if (!active) return;
        setJob(result); setPollError(null);
        setSelected(previous => previous.filter(ip => result.results.some(row => row.ip === ip && !row.exists)));
        if (result.status === 'running') timer = setTimeout(() => { void poll(); }, 1000);
      } catch (error) { if (active) setPollError(failure(error)); }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [admin, jobId, retry]);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void start.run(async () => {
      const response = await api.post<{ id: string | number }>('/api/discovery', { cidr: String(form.get('cidr')), ports: String(form.get('ports')) });
      setParams({ job: String(response.id) });
    }, undefined, 'Đã bắt đầu quét mạng.');
  }
  if (!admin) return <div className="nm-error-box" role="alert">Chỉ quản trị viên được quét mạng.</div>;
  const running = job?.status === 'running';
  return <><div className="nm-page-head"><h1>Quét mạng</h1></div><Panel title="Phát hiện thiết bị"><form onSubmit={submit}><Notice mutation={start} /><Field label="Dải IP (CIDR) *" name="cidr" error={start.error?.errors} hint="Chỉ IPv4, tối đa /22 (1.024 địa chỉ)."><input className="form-control ip" id="cidr" name="cidr" required placeholder="Nhập dải IPv4/CIDR" pattern="(?:[0-9]{1,3}\.){3}[0-9]{1,3}/(?:2[2-9]|3[0-2])" disabled={running || start.pending} /></Field><Field label="Cổng kiểm tra *" name="ports" error={start.error?.errors} hint="Danh sách cổng phân cách bởi dấu phẩy, từ 1 đến 65535."><input className="form-control" id="ports" name="ports" required placeholder="Nhập cổng cần kiểm tra" disabled={running || start.pending} pattern="[0-9]+(?:\s*,\s*[0-9]+)*" /></Field><div className="nm-form-actions"><button className="btn btn-primary" type="submit" disabled={running || start.pending || Boolean(jobId && !job && !pollError)}>{start.pending ? 'Đang bắt đầu…' : 'Bắt đầu quét'}</button></div></form></Panel>
    {jobId && <Panel title="Tiến trình quét"><Errors error={pollError} />{pollError && <button className="btn btn-secondary" onClick={() => setRetry(value => value + 1)}>Thử lại</button>}{!job && !pollError && <p role="status">Đang tải tiến trình…</p>}{job && <><div className="d-flex align-items-center gap-3 mb-3"><progress value={job.completed} max={Math.max(job.total, 1)} aria-label="Tiến trình quét" style={{ width: 320 }} /><span role="status">{job.completed} / {job.total} · tìm thấy {job.results.length} · {({ running: 'Đang quét', completed: 'Hoàn tất', stopped: 'Đã dừng', failed: 'Quét thất bại' })[job.status]}</span>{running && <button className="btn btn-secondary" disabled={stop.pending} onClick={() => void stop.run(() => api.post(`/api/discovery/${encodeURIComponent(String(job.id))}/stop`, {}), () => setRetry(value => value + 1), 'Đã yêu cầu dừng quét.')}>Dừng</button>}</div><Notice mutation={stop} /><form onSubmit={event => { event.preventDefault(); void imports.run(() => api.post(`/api/discovery/${encodeURIComponent(String(job.id))}/import`, { ips: selected, group_id: Number(groupId) }), () => { setSelected([]); setRetry(value => value + 1); }, 'Đã thêm thiết bị vào kho.'); }}><Notice mutation={imports} /><div className="table-responsive"><table className="nm-table"><thead><tr><th><input aria-label="Chọn tất cả thiết bị mới" type="checkbox" checked={job.results.some(row => !row.exists) && job.results.filter(row => !row.exists).every(row => selected.includes(row.ip))} onChange={event => setSelected(event.target.checked ? job.results.filter(row => !row.exists).map(row => row.ip) : [])} /></th><th>IP</th><th>Hostname</th><th>Cổng mở</th><th>Đoán loại</th><th>Trong kho</th></tr></thead><tbody>{job.results.map(row => <tr key={row.ip} className={row.exists ? 'row-muted' : ''}><td><input type="checkbox" disabled={row.exists || imports.pending} checked={!row.exists && selected.includes(row.ip)} aria-label={`Chọn ${row.ip}`} onChange={event => setSelected(previous => event.target.checked ? [...previous, row.ip] : previous.filter(ip => ip !== row.ip))} /></td><td className="ip">{row.ip}</td><td>{row.hostname || '–'}</td><td>{row.ports.join(', ') || '–'}</td><td>{row.type || '–'}</td><td>{row.exists ? 'Đã có' : 'Chưa có'}</td></tr>)}{!job.results.length && <Empty columns={6} text={running ? 'Đang tìm thiết bị…' : 'Không tìm thấy thiết bị.'} />}</tbody></table></div><LoadState resource={groups} /><div className="nm-toolbar"><span>Đã chọn {selected.length}</span><label htmlFor="group_id">Thêm vào nhóm</label><select id="group_id" className="form-select" style={{ width: 240 }} required value={groupId} onChange={event => setGroupId(event.target.value)}><option value="">Chọn nhóm</option>{groups.data?.groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select><button className="btn btn-primary" disabled={!selected.length || !groupId || imports.pending || running} type="submit">{imports.pending ? 'Đang thêm…' : 'Thêm vào kho'}</button></div>{running && <p className="muted">Chờ quét hoàn tất hoặc dừng quét trước khi nhập kết quả.</p>}</form></>}</Panel>}
  </>;
}
