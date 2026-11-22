import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { Field, Notice, Panel, useMutation } from './operations';

export default function Login() {
  const { user, loading, login } = useAuth();
  const navigate = useNavigate();
  const mutation = useMutation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void mutation.run(() => login(username, password), () => { setPassword(''); navigate('/', { replace: true }); }, '');
  }
  if (loading) return <p className="nm-loading" role="status">Đang kiểm tra phiên đăng nhập…</p>;
  if (user) return <Navigate to="/" replace />;
  return <div className="nm-login-wrap"><div className="nm-login"><Panel title="NetMon — Đăng nhập"><form onSubmit={submit}><Notice mutation={mutation} /><Field label="Tên đăng nhập" name="username" error={mutation.error?.errors}><input className="form-control" id="username" name="username" autoComplete="username" autoFocus required value={username} onChange={event => setUsername(event.target.value)} /></Field><Field label="Mật khẩu" name="password" error={mutation.error?.errors}><input className="form-control" id="password" name="password" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /></Field><div className="nm-form-actions"><button className="btn btn-primary" disabled={mutation.pending} type="submit">{mutation.pending ? 'Đang đăng nhập…' : 'Đăng nhập'}</button></div></form></Panel></div></div>;
}
