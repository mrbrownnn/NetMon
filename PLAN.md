# NetMon – Kế hoạch triển khai & hợp đồng module

Spec gốc: `NetMon – PRD & SRS.md`, `UI-DESIGN.md`. Python 3.11, venv `.venv` (đã cài requirements.txt).
Chạy test: `.venv/Scripts/python -m pytest -q`.

## Cấu trúc package (mỗi agent CHỈ sửa thư mục của mình)

```
netmon/
  domain/            # T1 – thuần Python, KHÔNG import flask/sqlalchemy
    status.py        # Status enum, CheckResult dataclass, worst()
    nodes.py         # NetworkNode(ABC) ← Group, Device ← Router/Switch/Server/PC/Printer; DeviceFactory
    sensors/         # Sensor(ABC) + Ping/Port/Http/Dns/Snmp; SensorFactory; SensorObserver
    alerts.py        # Alert, AlertLevel, AlertState, AlertManager(SensorObserver), Notifier(ABC) + Log/Email/Telegram/Web
    scheduler.py     # MonitorScheduler (Singleton, ThreadPoolExecutor)
    repositories.py  # Repository ABC + InMemory* impl (cho test)
    remote/          # T2 – Connection(Strategy), DeviceDriver(Adapter), ConfigCommand(Command), CommandHistory, DriverFactory
  infra/             # T3 – SQLAlchemy models + Sql*Repository, crypto (Fernet), config (.env)
  services/          # T3 – NetMonService Facade: inventory, monitor, alert, config, report, discovery, audit, auth
  web/               # T4 – Flask app factory, routes, templates, static, SocketIO
tests/               # mỗi agent viết test cho phần mình: tests/test_<module>.py
run.py               # entry: python run.py
```

## Hợp đồng chung (bắt buộc dùng đúng tên)

```python
# netmon/domain/status.py
class Status(str, Enum): UP="UP"; WARNING="WARNING"; DOWN="DOWN"; PAUSED="PAUSED"; UNKNOWN="UNKNOWN"
SEVERITY = {UP:0, PAUSED:0, UNKNOWN:1, WARNING:2, DOWN:3}
def worst(statuses: Iterable[Status]) -> Status   # rỗng -> UNKNOWN; toàn PAUSED -> PAUSED
@dataclass(frozen=True) class CheckResult: status: Status; value: float|None; message: str; ts: datetime

# netmon/domain/sensors/base.py
class SensorObserver(Protocol): def on_status_changed(self, sensor, old: Status, result: CheckResult) -> None
                                 def on_result(self, sensor, result: CheckResult) -> None   # mỗi lần check
class Sensor(ABC):
    type_name: ClassVar[str]; params_schema: ClassVar[dict]   # schema field cho form UI (name->{label,type,default})
    __init__(self, id: int|None, device_id: int, name: str, target: str, interval=30, timeout=5.0,
             warning_threshold: float|None=None, down_after=3, params: dict|None=None, paused=False)
    run() -> CheckResult          # Template Method: check() -> _apply_threshold -> đếm lỗi liên tiếp -> _update_status
    check() -> CheckResult        # abstract
    pause()/resume(); status, last_result, paused (property)
    attach(observer)/detach(observer)
class SensorFactory: register(name) decorator; create(type_name, **kw); types() -> dict[str, type[Sensor]]

# netmon/domain/nodes.py
class NetworkNode(ABC): id, name, parent; status (abstract property)
class Group(NetworkNode): children; add(node); remove(node); status = worst(children); is_ancestor_of(node) (chống vòng FR-14)
class Device(NetworkNode): ip (property validate IPv4 -> ValueError), mac, vendor, location, notes, extra: dict, sensors
    device_type: ClassVar[str]; extra_fields: ClassVar[dict]; default_sensors() -> list[dict]  # [{"type":"ping",...}]
DeviceFactory.register("router") ...; create(device_type, **kw); types()

# netmon/domain/remote/
class Connection(ABC): connect(); send_command(cmd)->str; send_config(cmds: list[str])->str; close(); __enter__/__exit__
   SSHConnection, TelnetConnection (netmiko), FakeConnection (trạng thái giả trong RAM: hostname, interfaces, routes)
class ConnectionError_(Exception) có .kind in {"timeout","auth","refused","other"}
class DeviceDriver(ABC): netmiko_type; get_running_config(); get_interfaces()->list[dict(name,ip,status,description)];
   get_routes()->list[dict]; cmd_set_hostname(name)->list[str]; cmd_set_interface_ip(iface, cidr)->list[str];
   cmd_toggle_interface(iface, enable)->list[str]
   VyOSDriver, MikroTikDriver, CiscoIOSDriver; DriverFactory.register("vyos")...
class ConfigCommand(ABC): preview()->list[str]; execute(conn)->str; undo_commands()->list[str]; describe()->str
   SetHostname, SetInterfaceIP, ToggleInterface (giữ giá trị cũ để undo)
class CommandHistory: push(cmd); can_undo(cmd_id) chỉ khi là mới nhất chưa undo; undo_last(conn)
```

## Service Facade (T3 cung cấp cho T4) – `netmon/services/facade.py`
`NetMonService` gom: `auth`, `inventory`, `monitor`, `alerts`, `reports`, `config`, `discovery`, `audit`, `settings`.
Trả về dict/dataclass thuần (JSON-able), KHÔNG trả password. Lỗi validate -> `ValidationError(field_errors: dict)`.
Lỗi quyền xử lý ở tầng web. `NetMonService.create(db_url, fernet_key, publisher)`; `publisher(event:str, data:dict)` callback để web đẩy SocketIO
(event: `sensor_status_changed`, `sensor_result`, `alert_opened`, `alert_updated`).

## Task & phân công

| Task | Agent | Phụ thuộc |
|---|---|---|
| T1 domain core + test (≥70% cover) | sonnet | – |
| T2 remote (connection/driver/command) + test | sonnet | – |
| T3 infra + services facade + test | sonnet | T1,T2 (code theo hợp đồng trên) |
| T4 web UI (Flask, templates, static, SocketIO) | sonnet | T3 (code theo hợp đồng) |
| R review + tích hợp + chạy TC | opus | tất cả |

Đợt 1 chạy song song T1, T2, T4-tĩnh (css/templates/macros). Đợt 2: T3. Đợt 3: T4 nối route. Đợt 4: Opus review.

## Deploy (Railway) & test
- Không có CI: mọi agent chạy test local `.venv/Scripts/python -m pytest -q` trước khi báo xong.
- `run.py` phải expose `app` (Flask app đã gắn SocketIO, scheduler start lúc tạo app, 1 lần) và `if __name__ == "__main__": socketio.run(app)`.
- Route `GET /healthz` -> 200 `{"ok": true}`, không cần login.
- Env: `SECRET_KEY`, `FERNET_KEY` (nếu thiếu: dev tự sinh + cảnh báo log), `DATABASE_URL` (mặc định `sqlite:///netmon.db`), `ADMIN_USERNAME`/`ADMIN_PASSWORD` (seed admin khi DB rỗng), `PORT`.
- Gunicorn 1 worker nhiều thread (scheduler singleton trong process). SocketIO `async_mode="threading"`.
