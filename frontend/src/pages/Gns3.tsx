import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import { Empty, LoadState, Notice, Panel, Status, roleName, useLoad, useMutation } from './operations';

type Project = { project_id: string; name: string; status: string };
type Overview = { configured: boolean; demo: boolean; url: string | null; version: string | null; error: string | null; projects: Project[] };
type Node = { node_id: string; name: string; node_type: string; status: string; console_host?: string; console?: number | null; console_type?: string;
  device: { id: number; name: string; ip: string; status: string } | null };
type Link_ = { link_id: string; ends: { node_id: string; node_name: string; adapter_number: number | null; port_number: number | null; label: string }[] };
type Topology = { nodes: Node[]; links: Link_[] };

// GNS3 node states -> NetMon status colours (only status carries colour).
const nodeStatus = (status: string) => ({ started: 'UP', stopped: 'DOWN', suspended: 'PAUSED' }[status] ?? 'UNKNOWN');
const port = (end: Link_['ends'][number]) => end.label || `${end.adapter_number ?? '?'}/${end.port_number ?? '?'}`;

export default function Gns3() {
  const { user } = useAuth();
  const admin = roleName(user?.role) === 'admin';
  const overview = useLoad<Overview>('/api/gns3');
  const [projectId, setProjectId] = useState('');
  const projects = overview.data?.projects ?? [];
  useEffect(() => { if (!projectId && projects.length) setProjectId(projects[0].project_id); }, [projectId, projects]);
  const topology = useLoad<Topology>(projectId ? `/api/gns3/projects/${projectId}` : null);
  const mutation = useMutation();

  useEffect(() => {  // node state changes outside NetMon too: refresh every 10 s while the page is open
    if (!projectId) return;
    const timer = window.setInterval(topology.reload, 10000);
    return () => window.clearInterval(timer);
  }, [projectId, topology.reload]);

  function act(node: Node, action: 'start' | 'stop' | 'reload') {
    const label = { start: 'Bật', stop: 'Tắt', reload: 'Khởi động lại' }[action];
    if (action !== 'start' && !window.confirm(`${label} node ${node.name}? Thiết bị ảo sẽ ${action === 'stop' ? 'ngừng hoạt động' : 'khởi động lại'}.`)) return;
    void mutation.run(() => api.post(`/api/gns3/projects/${projectId}/nodes/${node.node_id}/${action}`, {}), topology.reload, `${label} node ${node.name}: đã gửi lệnh.`);
  }

  const data = overview.data;
  const nodes = topology.data?.nodes ?? [];
  const links = topology.data?.links ?? [];
  return <>
    <div className="nm-page-head"><h1>GNS3</h1></div>
    <LoadState resource={overview} />
    {data && <Panel title="Kết nối GNS3">
      {!data.configured ? <p className="mb-0">Chưa cấu hình. Đặt biến môi trường <code>GNS3_URL</code> (ví dụ <code>http://127.0.0.1:3080</code>, GNS3 2.2) rồi khởi động lại NetMon. Đặt <code>GNS3_URL=demo</code> để dùng lab giả lập.</p>
        : <div className="d-flex gap-4 flex-wrap align-items-center">
          <span>Server <strong>{data.demo ? 'Lab giả lập (demo)' : data.url}</strong></span>
          <span>Phiên bản <strong>{data.version ?? '–'}</strong></span>
          {data.error ? <span className="nm-form-error" role="alert">{data.error}</span> : <Status value="UP" />}
          {projects.length > 0 && <label className="d-flex gap-2 align-items-center">Project <select className="form-select" value={projectId} onChange={event => setProjectId(event.target.value)}>
            {projects.map(project => <option key={project.project_id} value={project.project_id}>{project.name} ({project.status})</option>)}</select></label>}
        </div>}
      {data.demo && <p className="nm-form-hint mb-0 mt-2">Lab giả lập: node, link và lệnh bật/tắt chỉ thay đổi trong bộ nhớ, không có máy ảo thật.</p>}
    </Panel>}
    <Notice mutation={mutation} />
    {projectId && <>
      <LoadState resource={topology} />
      <Panel title={`Node (${nodes.length})`}><div className="table-responsive"><table className="nm-table">
        <thead><tr><th>Trạng thái</th><th>Tên</th><th>Loại</th><th>Console</th><th>Thiết bị NetMon</th>{admin && <th>Thao tác</th>}</tr></thead>
        <tbody>{nodes.map(node => <tr key={node.node_id}>
          <td><Status value={nodeStatus(node.status)} /> <span className="muted">{node.status}</span></td>
          <td>{node.name}</td><td>{node.node_type}</td>
          <td>{node.console && node.console_type !== 'none' ? <span className="mono">{node.console_type} {node.console_host}:{node.console}</span> : '–'}</td>
          <td>{node.device ? <><Link to={`/devices/${node.device.id}?tab=config`}>{node.device.name}</Link> <span className="ip">{node.device.ip}</span> <Status value={node.device.status} /></>
            : <span className="muted">Chưa ghép (tạo thiết bị cùng tên để xem cấu hình)</span>}</td>
          {admin && <td className="text-nowrap">{node.status === 'started'
            ? <><button type="button" className="btn btn-link btn-sm" disabled={mutation.pending} onClick={() => act(node, 'reload')}>Khởi động lại</button>
              <button type="button" className="btn btn-danger btn-sm" disabled={mutation.pending} onClick={() => act(node, 'stop')}>Tắt</button></>
            : <button type="button" className="btn btn-secondary btn-sm" disabled={mutation.pending} onClick={() => act(node, 'start')}>Bật</button>}</td>}
        </tr>)}{!nodes.length && !topology.loading && <Empty columns={admin ? 6 : 5} text="Project chưa có node." />}</tbody>
      </table></div></Panel>
      <Panel title={`Link (${links.length})`}><div className="table-responsive"><table className="nm-table">
        <thead><tr><th>Node A</th><th>Cổng A</th><th>Node B</th><th>Cổng B</th></tr></thead>
        <tbody>{links.map(link => { const [a, b] = link.ends; return <tr key={link.link_id}>
          <td>{a?.node_name ?? '–'}</td><td className="mono">{a ? port(a) : '–'}</td><td>{b?.node_name ?? '–'}</td><td className="mono">{b ? port(b) : '–'}</td></tr>; })}
          {!links.length && !topology.loading && <Empty columns={4} text="Project chưa có link." />}</tbody>
      </table></div></Panel>
    </>}
  </>;
}
