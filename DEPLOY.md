# Triển khai Railway

## Giới hạn kết nối

Railway không tự truy cập được mạng lab riêng trên laptop (ví dụ `192.168.100.0/24`). Muốn giám sát lab thật, cần kết nối mạng riêng/VPN hoặc chạy NetMon local cùng mạng lab. Không mở SSH/Telnet lab ra Internet chỉ để demo. Chế độ fake, nếu bật rõ ràng, chỉ dùng trình diễn cấu hình; không chứng minh thiết bị thật hoạt động.

## Cấu hình Railway

1. Tạo service từ repository GitHub này. Railway đọc `railway.json`, build `Dockerfile`.
2. Gắn volume vào `/data`. SQLite nằm tại `/data/netmon.db`; thiếu volume sẽ mất DB khi container bị thay.
3. Đặt biến môi trường riêng, không đưa secret vào git:
   - `SECRET_KEY`: khóa session ngẫu nhiên, ổn định qua các lần deploy.
   - `FERNET_KEY`: khóa mã hóa thông tin thiết bị, ổn định qua các lần deploy.
   - `ADMIN_USERNAME`: tài khoản quản trị ban đầu.
   - `ADMIN_PASSWORD`: mật khẩu mạnh riêng, chỉ dùng khởi tạo DB trống.
   - `DATABASE_URL=sqlite:////data/netmon.db`.
4. Chỉ chạy **1 replica, 1 Gunicorn worker**. Scheduler nằm trong process; tăng số worker sẽ nhân đôi lượt check.
5. Healthcheck `/healthz` chỉ xác nhận HTTP server hoạt động, không chứng minh lab có thể kết nối.
6. Kiểm tra đăng nhập, thêm thiết bị trong mạng được phép, chờ kết quả sensor thật và xem audit log sau deploy.

Tạo khóa local (không gửi kết quả vào chat hoặc commit):

```powershell
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Sao lưu DB cùng khóa Fernet bằng kênh bảo mật riêng. Mất khóa Fernet sẽ không giải mã được mật khẩu thiết bị đã lưu. Thay `ADMIN_PASSWORD` trong môi trường không tự đổi mật khẩu tài khoản đã tồn tại.

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
