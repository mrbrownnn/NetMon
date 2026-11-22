# Triển khai Railway

## Giới hạn kết nối

Railway không tự truy cập được mạng lab riêng trên laptop (ví dụ `192.168.100.0/24`). Muốn giám sát lab thật, cần kết nối mạng riêng/VPN hoặc chạy NetMon local cùng mạng lab. Không mở SSH/Telnet lab ra Internet chỉ để demo. Chế độ fake, nếu bật rõ ràng, chỉ dùng trình diễn cấu hình; không chứng minh thiết bị thật hoạt động.

## Cấu hình Railway (đang chạy)

Project có 2 service: **NetMon** (build `Dockerfile`) và **Postgres** (template Railway, có volume riêng).

1. Biến của NetMon:
   - `DATABASE_URL=${{Postgres.DATABASE_URL}}`: tham chiếu sang Postgres qua mạng nội bộ `railway.internal`. App tự đổi `postgres://`/`postgresql://` sang driver psycopg 3.
   - `SECRET_KEY`: khóa session ngẫu nhiên, ít nhất 32 ký tự, ổn định qua các lần deploy.
   - `FERNET_KEY`: khóa mã hóa mật khẩu thiết bị, ổn định qua các lần deploy.
   - `ADMIN_USERNAME`, `ADMIN_PASSWORD`: tài khoản quản trị tạo lần đầu khi DB trống (mật khẩu ít nhất 12 ký tự). Đổi mật khẩu trong app (menu Đổi mật khẩu); sửa biến môi trường sau đó **không** đổi mật khẩu tài khoản đã có.
   Thiếu hoặc yếu một trong các biến trên thì app từ chối khởi động (log ghi rõ biến nào).
2. Chỉ chạy **1 replica, 1 Gunicorn worker**. Scheduler nằm trong process; tăng số worker sẽ nhân đôi lượt check.
3. Healthcheck `/healthz` chỉ xác nhận HTTP server hoạt động, không chứng minh lab có thể kết nối.

Dùng SQLite thay Postgres vẫn được: gắn volume vào `/data` và đặt `DATABASE_URL=sqlite:////data/netmon.db`.

Tạo khóa local (không gửi kết quả vào chat hoặc commit):

```powershell
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Sao lưu DB (Postgres: `pg_dump`) cùng khóa Fernet bằng kênh bảo mật riêng. Mất khóa Fernet sẽ không giải mã được mật khẩu thiết bị đã lưu. Thay `ADMIN_PASSWORD` trong môi trường không tự đổi mật khẩu tài khoản đã tồn tại.

## Kiểm tra local, không CI

```powershell
.venv\Scripts\python -m pytest -q
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Docker daemon phải chạy trước khi dùng:

```powershell
docker build -t netmon:local .
```

Cấu hình build đang được chuyển sang React + TypeScript. Kết quả nghiệm thu cuối sẽ ghi rõ bước nào đã chạy, bước nào bị chặn bởi môi trường.
