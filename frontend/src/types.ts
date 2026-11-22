export type Role = 'admin' | 'operator' | 'viewer';
export interface User { id: number; username: string; role: Role }
export interface Session { user: User | null; csrf_token: string }
export type Status = 'UP' | 'WARNING' | 'DOWN' | 'PAUSED' | 'UNKNOWN';
export type StatusCounts = Partial<Record<Status | 'total', number>>;
export interface StatusEvent {
  sensor_id?: number;
  device_id?: number;
  new?: Status;
  old?: Status;
  value?: number | null;
  message?: string;
  counts?: StatusCounts;
  open_count?: number;
}
