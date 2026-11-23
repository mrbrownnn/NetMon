# NetMon

Ứng dụng giám sát và cấu hình thiết bị trong mạng lab được phép quản trị. Kiến trúc hiện tại theo `PLAN.md`: **React + TypeScript + Vite** (Bootstrap 5) cho frontend; **Flask REST API + Socket.IO** cho backend. Backend phục vụ assets từ `frontend/dist` sau build. UI Jinja/vanilla JS trong thiết kế ban đầu không phải hướng triển khai SPA mới.

TypeScript giúp kiểm tra kiểu dữ liệu API và sự kiện realtime khi phát triển; React tổ chức trạng thái, form và màn hình bằng component; Vite hỗ trợ dev server và build assets. Kiểm tra kiểu không thay thế kiểm thử tích hợp hoặc xác thực dữ liệu phía server.

Sơ đồ kiến trúc: [ARCHITECTURE.md](ARCHITECTURE.md). Bộ sơ đồ phân tích & thiết kế (use case, phân rã chức năng, block, lớp, ERD, DFD, sequence, state, activity, deployment): [docs/diagrams.md](docs/diagrams.md).

## Trạng thái

Đã tích hợp domain, service, REST API, Socket.IO và frontend React. Kiểm thử local (22/11/2026):
- 131 test Python pass (coverage toàn bộ `netmon` 92%); typecheck, build và 5 test frontend pass.
- `scripts/acceptance.py` lái app thật bằng trình duyệt headless: 43/43 kiểm tra pass, phủ TC-01→TC-16 (trừ phần cần lab). Thiết bị "chết/sống" được mô phỏng bằng một cổng TCP local; cấu hình từ xa chạy qua `FakeConnection`.
- Test service + web chạy được trên cả SQLite và PostgreSQL 16 (`NETMON_TEST_DB=postgresql://...`); nghiệm thu bằng trình duyệt pass trên Postgres.
- Toàn bộ pytest chạy trong container Linux build từ `Dockerfile` (134 test SQLite, 36 test service+web trên Postgres 16); nghiệm thu trình duyệt 43/43 trên stack `docker compose` (Gunicorn production + Postgres).
- Docker image build được; container chạy Gunicorn ở chế độ production, dữ liệu giữ qua restart volume `/data`, scheduler tự chạy lại, xuất PDF tiếng Việt, từ chối khởi động khi khóa/mật khẩu yếu.
- Chưa kiểm thử với lab ảo thật (SSH/Telnet/SNMP tới VyOS/MikroTik) và chưa gửi Telegram/email thật.

Phạm vi Must/Should trong `NetMon – PRD & SRS.md` đã có mã và test tự động; phần cần lab thật vẫn chưa xác minh end-to-end: xác thực và phân quyền, kiểm kê và nhóm thiết bị, sensor và scheduler, cảnh báo và realtime, báo cáo, discovery, cấu hình từ xa, audit và thiết lập. Xem spec để biết mức ưu tiên từng chức năng; không suy diễn rằng mọi chức năng đã được hỗ trợ đầy đủ.

## Yêu cầu

- Python **3.11+**, Node.js **22+** và npm.
- Lệnh `ping` của hệ điều hành; quyền kết nối tới thiết bị trong lab.
- PowerShell trên Windows cho các ví dụ dưới đây. Không cần kích hoạt venv nếu gọi Python bằng đường dẫn đầy đủ.
- Docker chỉ cần khi kiểm tra image hoặc triển khai container.

## Cài đặt local

Chạy tại thư mục gốc repository:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Sửa `.env` trước khi chạy. Không đưa `.env`, mật khẩu thiết bị hoặc khóa vào git. Đặt rõ:

```dotenv
SECRET_KEY=<khóa-session-ngẫu-nhiên-ổn-định>
FERNET_KEY=<khóa-Fernet-hợp-lệ-ổn-định>
ADMIN_USERNAME=<tài-khoản-quản-trị-tự-chọn>
ADMIN_PASSWORD=<mật-khẩu-mạnh-riêng>
DATABASE_URL=sqlite:///netmon.db
```

Các giá trị trong ngoặc nhọn là chỗ cần thay, không phải thông tin đăng nhập demo. Tạo khóa local, giữ riêng kết quả:

```powershell
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Giữ `SECRET_KEY` và `FERNET_KEY` ổn định qua restart/deploy. Khóa session thay đổi sẽ làm mất phiên đăng nhập; mất khóa Fernet sẽ không giải mã được mật khẩu thiết bị đã lưu. Không dựa vào khóa tự sinh hoặc tài khoản mặc định trong cấu hình phát triển. `ADMIN_PASSWORD` chỉ khởi tạo tài khoản khi DB trống; thay biến môi trường không tự đổi mật khẩu tài khoản đã tồn tại.

Build và chạy:

```powershell
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run build
.venv\Scripts\python run.py
```

`run.py` expose Flask `app` (Gunicorn dùng trên Railway) và chạy Socket.IO server ở cổng `PORT` (mặc định 5000). `SECRET_KEY` và `FERNET_KEY` là bắt buộc; thiếu sẽ báo lỗi ngay khi khởi động.

### Phát triển frontend

Chạy Flask tại cổng **5000** trong một terminal và Vite trong terminal khác:

```powershell
npm --prefix frontend run dev
```

Dùng địa chỉ Vite in trong terminal. Cấu hình Vite cần proxy request API và `/socket.io` tới `http://127.0.0.1:5000`, bật WebSocket cho Socket.IO; giữ session cookie và CSRF theo hợp đồng API. Build production không cần chạy Vite dev server.

## Kiểm thử local, không CI

```powershell
.venv\Scripts\python -m pytest tests -q --cov=netmon/domain --cov-report=term
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Nếu Docker daemon đang chạy:

```powershell
docker build -t netmon:local .
```

Test mock và fake không chứng minh mạng lab hoặc thiết bị thật hoạt động. Repository không yêu cầu tạo pipeline CI.

## Lab thật và chế độ fake

- **Lab thật:** sensor thực hiện ping/TCP/HTTP/DNS/SNMP theo loại; cấu hình từ xa dùng SSH hoặc Telnet với thông tin thiết bị được cấp quyền. Cần kết nối mạng thực từ máy chạy backend tới thiết bị.
- **Fake:** `netmon/domain/remote/connection.py` có `FakeConnection` giữ trạng thái giả trong RAM cho kiểm thử/trình diễn cấu hình. Phải chọn chế độ fake rõ ràng; không tự chuyển sang fake khi thiết bị thật lỗi. Kết quả fake không chứng minh cấu hình đã áp dụng lên thiết bị thật và không giả lập toàn bộ hoạt động giám sát.
- Telnet chỉ dùng được khi bản Netmiko đang cài hỗ trợ driver Telnet tương ứng; driver không hỗ trợ sẽ báo lỗi. Không mặc định mọi hãng đều dùng được Telnet. Ưu tiên SSH vì Telnet không mã hóa thông tin đăng nhập.
- Một số parser interface hiện suy ra trạng thái từ cấu hình quản trị (`shutdown`), không phải trạng thái link vận hành. Cần đối chiếu đầu ra lệnh operational trên thiết bị thật trước khi dùng dữ liệu này để kết luận cáp/link đang UP.
- Chỉ quét, giám sát và cấu hình thiết bị trong lab/mạng đã được cho phép. Không sử dụng ứng dụng để dò quét hay thay đổi hệ thống ngoài phạm vi ủy quyền.

## Chạy bằng Docker (giống Railway)

```powershell
Copy-Item .env.example .env   # điền SECRET_KEY, FERNET_KEY, ADMIN_PASSWORD
docker compose up --build     # http://localhost:8080
```

Đặt `NETMON_DEMO=1` trong `.env` để nạp dữ liệu demo một lần khi DB trống: 8 thiết bị với IP lab tự đặt (`192.168.100.x`), sensor đo thật tới host công cộng, lịch sử 7 ngày và cảnh báo cũ là dữ liệu sinh tự động. Trước khi go-live: tắt `NETMON_DEMO` và xóa thiết bị demo.

## Kết nối GNS3

Trang **GNS3** (menu chính) đọc GNS3 server **2.2** qua REST API `/v2`: danh sách project, node (loại, trạng thái, cổng console), link giữa các node. Admin bật/tắt/khởi động lại node (có hộp xác nhận, ghi audit log). Viewer/Operator chỉ xem.

- Cấu hình: biến `GNS3_URL`, ví dụ `http://127.0.0.1:3080`. Trống = tắt tính năng. GNS3 3.x (API `/v3`, cần token) chưa hỗ trợ.
- Xem cấu hình node: node được ghép với thiết bị NetMon **cùng tên**. Tạo thiết bị có IP quản lý + thông tin SSH của node, rồi bấm tên thiết bị trên trang GNS3 để mở tab Cấu hình (running-config, interface, routing qua SSH).
- Chỉ dùng được khi NetMon chạy cùng máy/mạng với GNS3 (chạy local). Railway không vào được GNS3 trên laptop.
- `GNS3_URL=demo`: lab giả lập 6 node, 6 link trong bộ nhớ, tên khớp dữ liệu demo. Đang bật trên Railway để trình diễn; bật/tắt node chỉ đổi trạng thái giả lập.

## Triển khai Railway

Xem quy trình đầy đủ trong [DEPLOY.md](DEPLOY.md).

- Một service build frontend bằng Node và chạy backend Python, phục vụ assets đã build.
- **Chỉ 1 replica, 1 Gunicorn worker**; scheduler nằm trong process, nhiều worker/replica sẽ tạo lượt check trùng. Socket.IO dùng threading.
- DB: service Postgres của Railway, `DATABASE_URL=${{Postgres.DATABASE_URL}}` (hoặc SQLite trên volume `/data`).
- Khai báo `SECRET_KEY`, `FERNET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` riêng và ổn định. Sao lưu DB cùng khóa Fernet qua kênh bảo mật riêng.
- `/healthz` chỉ kiểm tra HTTP server, không xác minh sensor hay kết nối lab.
- Railway không tự truy cập được mạng riêng trên laptop, ví dụ `192.168.100.0/24`. Chạy local cùng mạng lab hoặc thiết lập mạng riêng/VPN phù hợp. Không mở SSH/Telnet lab ra Internet chỉ để demo.

## Bản đồ OOP và pattern

| Mã nguồn | Vai trò |
| --- | --- |
| `netmon/domain/status.py` | Enum `Status`, `CheckResult` bất biến, tổng hợp trạng thái bằng `worst()` |
| `netmon/domain/nodes.py` | Composite `NetworkNode` → `Group`/`Device`; kế thừa Router/Switch/Server/PC/Printer; registry `DeviceFactory`; IP được kiểm tra qua property |
| `netmon/domain/sensors/base.py` | ABC `Sensor`; Template Method `run()`; Observer và registry `SensorFactory`; property kiểm tra interval/timeout/threshold |
| `netmon/domain/sensors/*.py` | Đa hình cho Ping/Port/HTTP/DNS/SNMP; pysnmp chỉ import khi cần |
| `netmon/domain/alerts.py` | `AlertManager` nhận sự kiện sensor; ABC `Notifier` và các kênh độc lập; lỗi một kênh không chặn kênh khác |
| `netmon/domain/scheduler.py` | Singleton `MonitorScheduler`, thread pool, lập lịch riêng theo interval sensor |
| `netmon/domain/repositories.py` | Repository ABC và lưu trữ trong RAM cho test; domain không phụ thuộc Flask/SQLAlchemy |
| `netmon/domain/remote/connection.py` | Strategy cho SSH/Telnet/Fake |
| `netmon/domain/remote/drivers.py` | Adapter cho lệnh và parser theo hãng; registry `DriverFactory` |
| `netmon/domain/remote/commands.py` | Command cho thay đổi cấu hình, lịch sử và undo |

Các giới hạn kỹ thuật khác hiện có: DNS dùng resolver hệ điều hành nên timeout sensor chưa giới hạn riêng thời gian phân giải; HTTP dùng urllib và đi theo redirect; SQLite và scheduler trong process phù hợp quy mô lab đơn instance, không phải kiến trúc giám sát phân tán.
