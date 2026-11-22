import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, loadSession } from './api';
import type { Session, User } from './types';

interface Auth {
  user: User | null;
  loading: boolean;
  error: string;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}
const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  async function refresh() {
    const session = await loadSession();
    setUser(session.user);
    setError('');
  }
  useEffect(() => {
    void refresh().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Không tải được phiên đăng nhập.')).finally(() => setLoading(false));
    const unauthorized = () => setUser(null);
    window.addEventListener('nm:unauthorized', unauthorized);
    return () => window.removeEventListener('nm:unauthorized', unauthorized);
  }, []);
  async function login(username: string, password: string) {
    const session = await api.post<Session>('/api/auth/login', { username, password });
    setUser(session.user);
  }
  async function logout() {
    await api.post('/api/auth/logout', {});
    setUser(null);
    await refresh();
  }
  return <AuthContext.Provider value={{ user, loading, error, login, logout, refresh }}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('useAuth requires AuthProvider');
  return auth;
}
