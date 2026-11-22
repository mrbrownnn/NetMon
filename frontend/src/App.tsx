import { useEffect, useState, type ReactNode } from 'react';
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { io } from 'socket.io-client';
import { api } from './api';
import { useAuth } from './auth';
import type { Role, StatusCounts, StatusEvent } from './types';
import Dashboard from './pages/Dashboard';
import Devices from './pages/Devices';
import DeviceForm from './pages/DeviceForm';
import DeviceDetail from './pages/DeviceDetail';
import Sensors from './pages/Sensors';
import SensorForm from './pages/SensorForm';
import SensorDetail from './pages/SensorDetail';
import Alerts from './pages/Alerts';
import Discovery from './pages/Discovery';
import Reports from './pages/Reports';
import Logs from './pages/Logs';
import Settings from './pages/Settings';
import Login from './pages/Login';
import ChangePassword from './pages/ChangePassword';

const menu: { path: string; label: string; role: Role }[] = [
  { path: '/', label: 'Trang chủ', role: 'viewer' },
  { path: '/devices', label: 'Thiết bị', role: 'viewer' },
  { path: '/sensors', label: 'Sensor', role: 'viewer' },
  { path: '/alerts', label: 'Cảnh báo', role: 'viewer' },
  { path: '/discovery', label: 'Quét mạng', role: 'admin' },
  { path: '/reports', label: 'Báo cáo', role: 'viewer' },
  { path: '/logs', label: 'Nhật ký', role: 'viewer' },
  { path: '/settings', label: 'Cài đặt', role: 'admin' },
];
const rank: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

function RequireRole({ children, role = 'viewer' }: { children: ReactNode; role?: Role }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (rank[user.role] < rank[role]) return <div className="alert alert-danger">Bạn không có quyền truy cập trang này.</div>;
  return children;
}

function QuickSearch() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<{ id: number; name: string; ip: string }[]>([]);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); setError(''); return; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void api.get<{ devices: typeof results }>(`/api/devices?q=${encodeURIComponent(query)}&page=1`, { signal: controller.signal })
        .then(data => { setResults(data.devices.slice(0, 8)); setError(''); })
        .catch((cause: unknown) => {
          if (!controller.signal.aborted) { setResults([]); setError(cause instanceof Error ? cause.message : 'Không tìm được thiết bị.'); }
        });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);
  return <form className="nm-search" role="search" onSubmit={event => {
    event.preventDefault();
    setOpen(false);
    navigate(`/devices?q=${encodeURIComponent(query.trim())}`);
  }} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }}>
    <input aria-label="Tìm thiết bị, IP" type="search" placeholder="Tìm thiết bị, IP..." value={query}
      onChange={event => { setQuery(event.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
      onKeyDown={event => { if (event.key === 'Escape') setOpen(false); }} aria-expanded={open && query.trim().length >= 2} aria-controls="quick-search-results" />
    {open && query.trim().length >= 2 && <div className="nm-suggest" id="quick-search-results">
      {results.map(device => <Link key={device.id} to={`/devices/${device.id}`} onClick={() => { setOpen(false); setQuery(''); }}>
        {device.name}<span className="ip">{device.ip}</span>
      </Link>)}
      {!results.length && <div className="nm-suggest-empty" role="status">{error || 'Không có kết quả'}</div>}
    </div>}
  </form>;
}

function Shell() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [counts, setCounts] = useState<StatusCounts>({});
  const [alertCount, setAlertCount] = useState(0);
  const [connected, setConnected] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!user) return;
    let active = true;
    const controller = new AbortController();
    const refreshCounts = () => {
      void api.get<{ status_counts: StatusCounts; open_alerts: unknown[]; open_alert_count?: number }>('/api/dashboard', { signal: controller.signal })
        .then(data => { if (active) { setCounts(data.status_counts); setAlertCount(data.open_alert_count ?? data.open_alerts.length); setError(''); } })
        .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : 'Không tải được tổng trạng thái.'); });
    };
    refreshCounts();
    const socket = io('/ws/status', { withCredentials: true, reconnectionDelay: 5000, reconnectionDelayMax: 5000 });
    socket.on('connect', () => { setConnected(true); setUpdated(new Date()); refreshCounts(); window.dispatchEvent(new CustomEvent('nm:status')); });
    socket.on('disconnect', () => setConnected(false));
    socket.on('connect_error', () => setConnected(false));
    for (const event of ['sensor_status_changed', 'sensor_result', 'alert_opened', 'alert_updated']) {
      socket.on(event, (data: StatusEvent) => {
        if (data.counts) setCounts(data.counts);
        if (data.open_count !== undefined) setAlertCount(data.open_count);
        setUpdated(new Date());
        document.dispatchEvent(new CustomEvent(`netmon:${event}`, { detail: data }));
        window.dispatchEvent(new CustomEvent('netmon:event', { detail: { event, data } }));
        window.dispatchEvent(new CustomEvent('nm:status', { detail: data }));
      });
    }
    return () => { active = false; controller.abort(); socket.disconnect(); };
  }, [user]);
  const current = menu.find(item => item.path === '/' ? location.pathname === '/' : location.pathname.startsWith(item.path));
  return <>
    <a className="visually-hidden-focusable" href="#main">Chuyển đến nội dung</a>
    <header className="nm-header">
      <Link className="nm-brand" to="/">NetMon</Link>
      <QuickSearch />
      <div className="nm-summary" aria-label="Tổng trạng thái sensor">
        {(['DOWN', 'WARNING', 'UP', 'PAUSED'] as const).map(status => <Link key={status} to={`/sensors?status=${status}`} hidden={!counts[status]}>
          <span className={`nm-sq st-${status.toLowerCase()}`}>{counts[status] || 0}</span> {status === 'WARNING' ? 'WARN' : status}
        </Link>)}
      </div>
      <div className="nm-user"><span>{user?.username} <span className="role">({user?.role})</span></span>{' '}
        <Link to="/account/password">Đổi mật khẩu</Link>{' '}
        <button type="button" onClick={() => { void logout().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Đăng xuất thất bại.')); }}>Đăng xuất</button>
      </div>
    </header>
    <nav className="nm-menu" aria-label="Điều hướng chính">
      {menu.filter(item => user && rank[user.role] >= rank[item.role]).map(item => <NavLink key={item.path} to={item.path} end={item.path === '/'}>
        {item.label}{item.path === '/alerts' && <span className={alertCount ? 'st-text-down' : ''}> ({alertCount})</span>}
      </NavLink>)}
    </nav>
    <nav className="nm-breadcrumb" aria-label="Đường dẫn"><Link to="/">Trang chủ</Link>{location.pathname !== '/' && <><span className="sep">›</span><span>{current?.label || 'Đổi mật khẩu'}</span></>}</nav>
    <main className="nm-main" id="main">
      {error && <div className="alert alert-warning" role="alert">{error}<button className="btn-close float-end" aria-label="Đóng" onClick={() => setError('')} /></div>}
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/devices" element={<Devices />} />
        <Route path="/devices/new" element={<RequireRole role="admin"><DeviceForm /></RequireRole>} />
        <Route path="/devices/:id/edit" element={<RequireRole role="admin"><DeviceForm /></RequireRole>} />
        <Route path="/devices/:id" element={<DeviceDetail />} />
        <Route path="/sensors" element={<Sensors />} />
        <Route path="/sensors/new" element={<RequireRole role="admin"><SensorForm /></RequireRole>} />
        <Route path="/sensors/:id/edit" element={<RequireRole role="admin"><SensorForm /></RequireRole>} />
        <Route path="/sensors/:id" element={<SensorDetail />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/discovery" element={<RequireRole role="admin"><Discovery /></RequireRole>} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/settings" element={<RequireRole role="admin"><Settings /></RequireRole>} />
        <Route path="/account/password" element={<ChangePassword />} />
        <Route path="*" element={<div className="alert alert-warning">Không tìm thấy trang. <Link to="/">Về trang chủ</Link></div>} />
      </Routes>
    </main>
    <footer className="nm-footer"><span>NetMon</span><span>·</span><span>Cập nhật lần cuối: {updated ? updated.toLocaleTimeString('vi-VN') : '–'}</span><span>·</span>
      <span className={connected ? 'connected' : ''} id="rt-status"><span className="nm-rt-dot" /> {connected ? 'Đã kết nối realtime' : 'Mất kết nối – đang thử lại…'}</span>
    </footer>
  </>;
}

export default function App() {
  const { loading, user, error, refresh } = useAuth();
  const location = useLocation();
  if (loading) return <main className="nm-main" role="status">Đang tải phiên đăng nhập…</main>;
  if (error) return <main className="nm-main"><div className="alert alert-danger" role="alert">{error}</div><button className="btn btn-primary" onClick={() => { void refresh().catch(() => undefined); }}>Thử lại</button></main>;
  if (!user) return location.pathname === '/login' ? <Login /> : <Navigate to="/login" replace />;
  if (location.pathname === '/login') return <Navigate to="/" replace />;
  return <Shell />;
}
