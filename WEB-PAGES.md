# React page integration contract

Latest user override replaces planned Jinja pages with React + TypeScript. All page components live in `frontend/src/pages`, export default, use React Router and shared `api` / `useAuth`. Existing shell owns assets, authentication state, routing and CSS. No Python routes changed here.

## Transport and authorization

`api.get<T>(url)`, `post<T>(url, body)`, `put<T>(url, body)`, `patch<T>(url, body)`, `delete<T>(url)` resolve decoded response body directly. Errors throw `Error` with `message` and optional `errors: Record<string,string>`. Backend JSON failures: `{message, errors?}`, HTTP 400/422 validation, 401 unauthenticated, 403 forbidden, 404 missing. Shared API adds CSRF and credentials. JSON mutations return updated resource or `{ok:true}`; create device/sensor returns `{id:number}`. Never include stored passwords/tokens in responses. Blank credential fields mean unchanged on update; server validates all fields.

`useAuth()` supplies `{user:{id,username,role}|null}`. Roles are lowercase `admin`, `operator`, `viewer`. UI hides inventory/settings/discovery mutation controls except admin; alert acknowledgment allowed admin/operator; config read allowed admin/operator; config mutation and terminal admin only. Server MUST independently enforce roles, including all export and config endpoints. No terminal integration is claimed without actual server support.

## Common shapes

- `pagination: {page:number,pages:number,total:number,per_page:number}` (1-based).
- `groups: Array<{id:number,name:string,parent_id?:number|null}>` (names may include hierarchy prefix).
- Status: `UP|WARNING|DOWN|PAUSED|UNKNOWN`; no last result means null, never a fabricated zero.
- Sensor: `{id,device_id,name,type,status,last_value:number|null,unit?,last_check:string|null,message?,interval,timeout,down_after,warning_threshold?,params?,paused?}`.
- Device: `{id,name,ip,device_type,status,group_id?,group_name?,mac?,vendor?,location?,notes?,extra?,sensors?:Sensor[],last_check?,protocol?,port?,username?,driver?}`.
- Tree: group nodes `{id,name,status,children:GroupNode[],devices:Device[]}`; root devices may be placed in a synthetic group only if clearly named ungrouped, not counted as stored group.
- History: `{ts:ISO8601,status,value:number|null,message:string}`; preserve chronological ordering. `history_summary` supplies real optional `uptime`, `down_count`, `down_seconds`, `average_ms`. Charts use latency only, single `#1F6FB2` line, 2px, Chart.js 4.4.8. Values for non-UP/WARNING become null and are not bridged. Accessible accompanying results table remains available.
- Schema maps: `device_types: Record<string,{label:string,extra_fields:Record<string,Field>,default_sensors?:unknown[]}>`; `sensor_types: Record<string,{label:string,params_schema:Record<string,Field>}>`. Field `{label,type,default?,required?,min?,max?,options?}`; supported types text/password/number/checkbox/select. Runtime registry is source of truth; backend validates same schema.

## Page loading and routes

| Component / browser route | GET JSON and response |
|---|---|
| Dashboard `/` | `/api/dashboard` → `{status_counts,open_alerts,top_latency,tree}` |
| Devices `/devices` | `/api/devices?q=&status=&type=&group_id=&page=` → `{devices,groups,tree,filters,pagination}` |
| DeviceForm `/devices/new`, `/devices/:id/edit` | `/api/devices/form[?id=]` → `{values,errors,device_types,groups,drivers,sensor_types}` |
| DeviceDetail `/devices/:id` | `/api/devices/:id?tab=&range=&sensor_id=` → `{device,sensors,history,history_summary,backups,config_history,logs,capabilities}` |
| Sensors `/sensors` | `/api/sensors?q=&status=&type=&group_id=&page=` → `{sensors,groups,status_counts,filters,pagination}` |
| SensorDetail `/sensors/:id` | `/api/sensors/:id?range=` → `{sensor,device,history,history_summary}` |
| SensorForm `/sensors/new`, `/sensors/:id/edit` | `/api/sensors/form[?id=&device_id=]` → `{values,errors,sensor_types,devices}` |
| Alerts `/alerts` | `/api/alerts?state=&level=&start=&end=&page=` → `{alerts,filters,pagination}` |
| Discovery `/discovery` | `/api/groups` → `{groups}`; resume job via `/api/discovery/:id` |
| Reports `/reports` | `/api/reports?range=&group_id=&start=&end=` → `{rows,summary,filters,groups,pdf_supported}` |
| Logs `/logs` | `/api/logs?user_id=&action=&start=&end=&page=` → `{logs,users,actions,filters,pagination}` |
| Settings `/settings` | `/api/settings?tab=users|groups|monitoring|system` → `{users,groups,values,errors,system}` |
| Login `/login` | Shell auth state; submit login endpoint below |
| ChangePassword `/account/password` | No initial payload; errors remain beside submitted fields |

`drivers` is a list of driver names (strings). Missing optional display fields render dash/empty state. Arrays must be arrays, not SQLAlchemy objects. All displayed timestamps ISO8601 at boundary; page localizes Vietnamese.

## Inventory mutations

- `POST /api/devices`: JSON `name,ip,device_type,group_id,mac,vendor,location,notes,extra,protocol,port,username,password,driver,default_sensors`. Returns `{id}`.
- `PUT /api/devices/:id`: same editable fields; empty password leaves credential unchanged. Returns device or `{ok:true}`.
- `DELETE /api/devices/:id`; confirmation required; returns `{ok:true}`.
- `POST /api/devices/:id/pause`, `/resume`: `{}` → `{ok:true}`.
- `POST /api/sensors`: JSON `device_id,type,name,interval,timeout,down_after,warning_threshold,params` → `{id}`.
- `PUT /api/sensors/:id`: editable fields above → sensor or `{ok:true}`.
- `DELETE /api/sensors/:id`; `POST /api/sensors/:id/pause`, `/resume`, `/check`: `{}` → `{ok:true}` or completed sensor result. Check button does not synthesize success readings; reload real data.

## Operations mutations and responses

- Alert `{id,level,state,created_at,device_id,device_name,sensor_id,sensor_name,old_status,new_status,duration_seconds?,ack_by?,note?}`.
- `POST /api/alerts/:id/ack` `{note}` → `{ok:true}`.
- `GET /api/alerts/channels` → `{channels:[{id,name,enabled,fields:[{name,label,type,value?}],last_test?}]}`. Secret field values omitted.
- `PUT /api/alerts/channels/:id` JSON enabled and schema-derived fields → `{ok:true}`; `POST /api/alerts/channels/:id/test` `{}` → `{message:string}`.
- `POST /api/discovery` `{cidr:string,ports:string}` → `{id:string|number}`. Server rejects networks larger than /22 and malformed port lists.
- `GET /api/discovery/:id` → `{id,status,completed,total,results:[{ip,hostname,ports:number[],type,exists:boolean}]}`. Status `running|completed|stopped|failed`; poll every second while running, stop on unmount. No invented ETA.
- `POST /api/discovery/:id/stop` `{}` → `{ok:true}`; `/import` `{ips:string[],group_id:number}` → `{ok:true,imported?:number}`. Existing devices cannot be selected.
- Reports rows `{device_id,device_name,group_name,uptime,down_count,down_seconds,average_ms,max_ms}`; summary `{device_count,uptime,down_count,down_seconds}`. Uptime percentage uses 0–100 scale. `GET /api/reports/export.csv` and `/export.pdf` accept same filters; CSV attachment, PDF shown only when `pdf_supported:true`.
- Audit log `{id,created_at,username,action,object,details}`. `users:[{id,username}]`, `actions:string[]`.
- Settings users `{id,username,role,locked,last_login?}`. `POST /api/settings/users` `{username,role,password}`; `PUT /api/settings/users/:id` `{username,role}`; `POST .../:id/lock`, `/unlock` `{}`; `/password` `{password}`. Each returns `{ok:true}`. Prevent accidental self-lock/demotion server-side.
- `POST /api/settings/groups` `{name,parent_id:number|null}`; `PUT /api/settings/groups/:id` same; `DELETE /api/settings/groups/:id`. Return `{ok:true}`; reject cycles and deleting nonempty groups.
- `PUT /api/settings/monitoring` `{default_interval,down_after,history_days,backup_time}` → `{ok:true}`.
- System `{version,scheduler_running,sensor_count,worker_count}`. `POST /api/settings/scheduler/restart` `{}` → `{ok:true}`.
- `POST /api/auth/login` `{username,password}` → auth user/session. Shell login method may wrap this call; page must refresh shared auth after success.
- `POST /api/account/password` `{current_password,new_password,confirm_password}` → `{ok:true}`. Never echo passwords in JSON errors.

## Remote config integration

Device response `capabilities:{config:boolean,terminal:boolean}` gates supported integration. Terminal explicitly reports unavailable until actual terminal transport exists. No fake terminal or hardcoded command output.

Base `/api/devices/:id/config`:
- `POST /connection` `{}` → `{ok:boolean,message:string,elapsed_ms?:number}`.
- `GET /running` → `{config:string}`.
- `GET /interfaces` → `{interfaces:[{name,ip,status,description}]}`.
- `GET /routes` → `{routes:[{destination,gateway,interface,metric?}]}`.
- `POST /preview` body `{command_type:'set_hostname'|'set_interface_ip'|'toggle_interface',params:{name}|{iface,cidr}|{iface,enable:boolean}}` → `{commands:string[],description?:string}`.
- `POST /execute` same body, after preview and explicit confirmation → `{output:string,backup_at?:string}`. Server must back up before execution and validate again; preview never authorizes bypassing permissions.
- `POST /backup` `{}` → `{backup:{id,created_at,size,config?}}`.
- `POST /undo` `{command_id:number}` → `{output:string}`. Server checks latest non-undone command only.

Device detail `backups:[{id,created_at,size,config}]`, `config_history:[{id,executed_at,username,description,commands:string[],undone:boolean,can_undo:boolean}]`. Real returned config allows local comparison/download; absent config must not generate empty fake backup.

Shell dispatches `window` event `nm:status` on real SocketIO sensor/alert events. Page load hooks may invalidate GET responses on this event, without resetting forms or inventing state.
