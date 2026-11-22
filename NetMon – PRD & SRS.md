# NetMon – PRD & SRS

Hệ thống kiểm kê và giám sát trạng thái mạng

Nov 22, 2026 · @Thanh

# PHẦN A – PRD (Product Requirements Document)

## 1. Tổng quan sản phẩm

NetMon là một web app viết bằng Python, gom vào một chỗ ba việc: kiểm kê thiết bị mạng, giám sát trạng thái theo thời gian thực và cấu hình thiết bị từ xa qua SSH/Telnet. Mô hình tổ chức lấy cảm hứng từ PRTG Network Monitor (Group → Device → Sensor), thu gọn cho vừa phạm vi đồ án môn OOP.

**Vấn đề cần giải quyết**

- Danh sách thiết bị (IP, MAC, vị trí, loại) thường nằm rải rác trong file Excel, hay sai và thiếu cập nhật.
- Thiết bị chết chỉ được phát hiện khi người dùng báo lỗi, không có cảnh báo chủ động.
- Muốn xem hoặc sửa cấu hình phải mở PuTTY vào từng con, không có lịch sử thay đổi để rollback.

**Mục tiêu**

1. Có một kho thiết bị tập trung, tìm và lọc được, hỗ trợ quét dải IP để phát hiện thiết bị.
2. Biết trạng thái từng thiết bị (UP / WARNING / DOWN) trong vòng 1 chu kỳ check (mặc định 30 giây), có cảnh báo khi trạng thái thay đổi.
3. Xem thông tin, backup và thay đổi cấu hình router/switch ngay trên web, có lịch sử và rollback.
4. Về mặt học thuật: thể hiện rõ 4 tính chất OOP, SOLID và tối thiểu 6 design pattern.

**Phạm vi**

| Trong phạm vi | Ngoài phạm vi |
| --- | --- |
| CRUD thiết bị, nhóm thiết bị dạng cây | Giám sát hàng nghìn thiết bị, phân tán nhiều probe |
| Sensor Ping, TCP Port, HTTP, DNS, SNMP (cơ bản) | NetFlow, phân tích lưu lượng, sơ đồ topology tự động |
| Cảnh báo qua web, log, email, Telegram | Ứng dụng di động, SMS |
| SSH/Telnet tới thiết bị trong lab ảo (VyOS, MikroTik CHR, FRR) | Thiết bị thật trong mạng sản xuất, Cisco IOS có bản quyền |
| Báo cáo uptime, xuất CSV/PDF | Phân quyền phức tạp, multi-tenant, SSO |

**Người dùng**

| Vai trò | Mô tả | Nhu cầu chính |
| --- | --- | --- |
| Admin | Quản trị viên mạng, toàn quyền | Quản lý thiết bị, cấu hình từ xa, quản lý tài khoản |
| Operator | Kỹ thuật viên trực hệ thống | Xem dashboard, xác nhận cảnh báo, xem cấu hình (không sửa) |
| Viewer | Giảng viên, quản lý | Xem dashboard và báo cáo |

## 2. Tính năng và độ ưu tiên

Các nhóm Must là bản tối thiểu để nộp được; Should và Could chỉ làm khi Must đã chạy ổn. Mã F-xx dùng để truy vết sang SRS.

| Mã | Module | Tính năng | Ưu tiên |
| --- | --- | --- | --- |
| F-01 | Xác thực | Đăng nhập, đăng xuất, phân quyền 3 vai trò | Must |
| F-02 | Kiểm kê | Thêm/sửa/xóa/xem thiết bị theo loại (Router, Switch, Server, PC, Printer) | Must |
| F-03 | Kiểm kê | Nhóm thiết bị dạng cây (tòa nhà → tầng → phòng) | Must |
| F-04 | Kiểm kê | Tìm kiếm, lọc theo loại/nhóm/trạng thái, sắp xếp | Must |
| F-05 | Kiểm kê | Nhập/xuất danh sách thiết bị bằng CSV | Should |
| F-06 | Kiểm kê | Quét dải IP (auto-discovery) và thêm thiết bị tìm được | Should |
| F-07 | Giám sát | Gắn sensor cho thiết bị: Ping, TCP Port, HTTP | Must |
| F-08 | Giám sát | Sensor DNS và SNMP (CPU, uptime, interface) | Could |
| F-09 | Giám sát | Chạy check định kỳ theo chu kỳ từng sensor, tạm dừng/tiếp tục | Must |
| F-10 | Giám sát | Ngưỡng WARNING/DOWN tuỳ chỉnh theo sensor | Must |
| F-11 | Giám sát | Dashboard realtime, tự cập nhật không cần F5 | Must |
| F-12 | Cảnh báo | Tạo cảnh báo khi trạng thái đổi, xác nhận (acknowledge) cảnh báo | Must |
| F-13 | Cảnh báo | Gửi thông báo qua email/Telegram | Should |
| F-14 | Báo cáo | Lịch sử check, biểu đồ độ trễ, uptime % theo ngày/tuần | Must |
| F-15 | Báo cáo | Xuất báo cáo CSV/PDF | Should |
| F-16 | Cấu hình từ xa | Lưu thông tin đăng nhập thiết bị (mã hoá) | Should |
| F-17 | Cấu hình từ xa | Xem thông tin: running-config, interface, routing table | Should |
| F-18 | Cấu hình từ xa | Backup cấu hình và so sánh 2 bản (diff) | Should |
| F-19 | Cấu hình từ xa | Thao tác có sẵn: đổi hostname, IP interface, bật/tắt interface, có rollback | Could |
| F-20 | Cấu hình từ xa | Terminal SSH/Telnet trên trình duyệt | Could |
| F-21 | Hệ thống | Nhật ký thao tác (audit log): ai làm gì, lúc nào | Should |

**User story tiêu biểu**

- Là Admin, tôi muốn quét dải 192.168.10.0/24 để thêm nhanh các thiết bị đang hoạt động mà không phải nhập tay.
- Là Operator, tôi muốn thấy ngay thiết bị nào chuyển sang DOWN trên dashboard và nhận tin Telegram, để xử lý trước khi người dùng báo.
- Là Operator, tôi muốn xác nhận một cảnh báo đang xử lý để đồng nghiệp không làm trùng.
- Là Admin, tôi muốn tắt một interface của router từ web và hoàn tác nếu mạng bị ảnh hưởng.
- Là Admin, tôi muốn backup cấu hình tất cả router mỗi ngày và xem bản hôm nay khác bản hôm qua ở đâu.
- Là Viewer, tôi muốn xuất báo cáo uptime tuần ra PDF để đính kèm báo cáo.

## 3. Giao diện web

Web gồm 10 trang, điều hướng bằng thanh menu bên trái. Trạng thái dùng màu thống nhất trên mọi trang: xanh lá = UP, vàng = WARNING, đỏ = DOWN, xám = PAUSED/UNKNOWN.

| Trang | Đường dẫn | Nội dung chính | Vai trò |
| --- | --- | --- | --- |
| Đăng nhập | `/login` | Form username/password, thông báo sai thông tin | Tất cả |
| Dashboard | `/` | 4 ô tổng số (UP / WARNING / DOWN / PAUSED), cây nhóm với chấm màu trạng thái, 10 cảnh báo mới nhất, top 5 thiết bị độ trễ cao nhất; tự cập nhật qua WebSocket | Tất cả |
| Danh sách thiết bị | `/devices` | Bảng thiết bị (tên, IP, loại, nhóm, trạng thái, lần check cuối), ô tìm kiếm, bộ lọc, nút Thêm / Nhập CSV / Xuất CSV | Tất cả (sửa: Admin) |
| Chi tiết thiết bị | `/devices/<id>` | 4 tab: **Tổng quan** (thông tin + sensor), **Lịch sử** (biểu đồ độ trễ 24h/7 ngày, uptime %), **Cấu hình** (xem config, backup, diff, thao tác nhanh), **Terminal** (SSH/Telnet trên web) | Tất cả (tab Cấu hình/Terminal: Admin) |
| Form thiết bị | `/devices/new`, `/devices/<id>/edit` | Chọn loại → form đổi trường theo loại (Switch có số port, Server có OS…), chọn nhóm, thông tin đăng nhập SSH/Telnet, sensor mặc định được tick sẵn | Admin |
| Nhóm | `/groups` | Cây nhóm kéo thả, thêm/đổi tên/xóa nhóm, trạng thái tổng của nhóm | Admin |
| Quét mạng | `/discovery` | Nhập dải IP (CIDR), thanh tiến trình, bảng kết quả (IP, hostname, port mở, đoán loại), tick chọn → thêm vào kho | Admin |
| Cảnh báo | `/alerts` | Danh sách cảnh báo lọc theo mức/trạng thái/thời gian, nút Xác nhận; tab cấu hình kênh thông báo (email, Telegram) | Admin, Operator |
| Báo cáo | `/reports` | Chọn khoảng thời gian + nhóm → bảng uptime, số lần DOWN, độ trễ trung bình; nút Xuất CSV/PDF | Tất cả |
| Quản trị | `/admin` | Quản lý tài khoản và vai trò, xem audit log, cài đặt chung (chu kỳ mặc định, thời gian giữ lịch sử) | Admin |

**Luồng 1 – Thiết bị chết và được xử lý**

1. Scheduler chạy PingSensor của Router R1, 3 lần liên tiếp không phản hồi.
2. Sensor chuyển UP → DOWN, thiết bị và nhóm chứa nó đổi màu đỏ trên dashboard.
3. AlertManager tạo cảnh báo và gửi Telegram cho Operator.
4. Operator bấm Xác nhận trên trang Cảnh báo, ghi chú "đang kiểm tra".
5. Khi R1 ping lại được, sensor chuyển về UP, cảnh báo tự đóng và gửi thông báo "đã khôi phục".

**Luồng 2 – Cấu hình từ xa có rollback**

1. Admin mở Chi tiết thiết bị R1 → tab Cấu hình.
2. Hệ thống tự backup running-config trước khi thay đổi.
3. Admin chọn "Tắt interface" → chọn eth1 → xem trước lệnh sẽ gửi → Xác nhận.
4. Lệnh chạy qua SSH, kết quả và lệnh được ghi vào lịch sử cấu hình.
5. Nếu có sự cố, Admin bấm Hoàn tác trên dòng lịch sử đó, hệ thống gửi lệnh ngược lại (bật eth1).

## 4. Tiêu chí thành công, lộ trình và rủi ro

Sản phẩm đạt khi demo trực tiếp được cả 2 luồng ở mục 3 trên lab ảo và báo cáo chỉ ra được từng tính chất OOP nằm ở class nào.

**Tiêu chí thành công**

- 100% tính năng Must hoạt động; tối thiểu 50% Should.
- Giám sát ổn định ít nhất 20 thiết bị / 50 sensor liên tục 1 giờ không lỗi.
- Thiết bị bị tắt trong lab hiển thị DOWN trên dashboard trong tối đa 2 chu kỳ check.
- Thêm 1 loại sensor mới chỉ bằng cách tạo 1 class mới + đăng ký vào Factory, không sửa class cũ (chứng minh Open/Closed).
- Độ phủ unit test phần domain (models, sensors, alerts) ≥ 70%.

**Lộ trình đề xuất (8 tuần)**

1. Tuần 1 – Phân tích: chốt PRD/SRS, vẽ use case và class diagram, dựng lab ảo (2 router + 1 switch + 1 server).
2. Tuần 2–3 – Lõi domain: Device, Group, Sensor, Status, Repository, Scheduler; chạy được bằng console.
3. Tuần 4 – Web cơ bản: đăng nhập, CRUD thiết bị/nhóm, dashboard realtime.
4. Tuần 5 – Cảnh báo và báo cáo: AlertManager, notifier, lịch sử, biểu đồ, xuất file.
5. Tuần 6 – Cấu hình từ xa: Connection, Driver, backup, diff, Command + rollback.
6. Tuần 7 – Bổ sung: auto-discovery, terminal web, SNMP (nếu kịp).
7. Tuần 8 – Đóng gói: test, sửa lỗi, viết báo cáo, quay video demo dự phòng.

**Rủi ro và cách xử lý**

| Rủi ro | Ảnh hưởng | Cách xử lý |
| --- | --- | --- |
| Lab ảo không kết nối được ra máy thật | Không demo được SSH/Telnet | Dựng lab ngay tuần 1; dự phòng `FakeConnection` trả dữ liệu mẫu |
| Máy yếu, chạy GNS3/EVE-NG chậm | Lab treo khi demo | Dùng containerlab hoặc giảm còn 2 node |
| Ping cần quyền root/admin trên một số hệ điều hành | PingSensor lỗi | Gọi lệnh `ping` của hệ điều hành qua subprocess thay vì raw socket |
| Phạm vi phình to | Trễ deadline | Khóa Must trước tuần 5; Could chỉ làm khi dư thời gian |
| Lộ mật khẩu thiết bị trong mã nguồn | Mất điểm bảo mật | Mã hoá bằng Fernet, khóa để trong `.env`, không commit lên git |

**Giả định**: hệ thống chạy trên 1 máy (laptop) cùng mạng với lab; số thiết bị ≤ 100; người dùng truy cập qua trình duyệt Chrome/Edge bản mới.

# PHẦN B – SRS (Software Requirements Specification)

## 5. Giới thiệu và kiến trúc

SRS này đặc tả chi tiết các yêu cầu của NetMon ở Phần A, làm cơ sở để thiết kế, lập trình và kiểm thử. Hệ thống theo kiến trúc phân tầng: tầng domain thuần Python, không phụ thuộc Flask hay cơ sở dữ liệu, nên test được độc lập và thay giao diện mà không sửa lõi.

**Thuật ngữ**

| Thuật ngữ | Ý nghĩa |
| --- | --- |
| Device | Một thiết bị mạng có địa chỉ IP (router, switch, server…) |
| Group | Nhóm chứa thiết bị hoặc nhóm con, ví dụ "Tầng 2 – Lab A" |
| Sensor | Một phép đo gắn với thiết bị (ping, port, HTTP…), chạy theo chu kỳ |
| Check | Một lần sensor thực hiện đo, sinh ra 1 CheckResult |
| Status | UP, WARNING, DOWN, PAUSED, UNKNOWN |
| Alert | Bản ghi sinh ra khi status của sensor thay đổi theo chiều xấu đi hoặc khôi phục |
| Driver | Lớp dịch thao tác chung (lấy config, tắt interface) sang lệnh riêng của từng hãng |
| Lab ảo | Mạng mô phỏng bằng GNS3 hoặc containerlab, dùng thay thiết bị thật |

**Công nghệ**

| Thành phần | Lựa chọn | Ghi chú |
| --- | --- | --- |
| Ngôn ngữ | Python 3.11+ | Bắt buộc theo môn học |
| Web | Flask + Jinja2 + Bootstrap 5 | Đơn giản, dễ trình bày; có thể thay FastAPI |
| Realtime | Flask-SocketIO | Đẩy trạng thái lên dashboard và terminal web |
| Biểu đồ | Chart.js | Độ trễ, uptime |
| CSDL | SQLite + SQLAlchemy | Một file, không cần cài server |
| Lập lịch | `concurrent.futures.ThreadPoolExecutor` | Chạy nhiều sensor song song |
| SSH/Telnet | Netmiko (dùng Paramiko bên dưới) | `telnetlib` đã bị gỡ khỏi Python 3.13 |
| SNMP | pysnmp | Chỉ khi làm F-08 |
| Terminal web | xterm.js | Chỉ khi làm F-20 |
| Mã hoá | `cryptography` (Fernet), `werkzeug.security` | Mật khẩu thiết bị và người dùng |
| Báo cáo PDF | ReportLab hoặc WeasyPrint | F-15 |
| Kiểm thử | pytest, pytest-cov |  |

**Môi trường lab ảo**

- Công cụ: GNS3 (nối ra máy thật qua node Cloud/NAT) hoặc containerlab (Linux/WSL2).
- Thiết bị: 2 router VyOS hoặc MikroTik CHR, 1 switch Open vSwitch, 1 server Linux chạy Nginx (để test HTTP sensor).
- Mạng quản lý: 192.168.100.0/24; mỗi thiết bị bật SSH, router bật thêm Telnet và SNMP v2c.
- Giới hạn: Cisco Packet Tracer không dùng được vì thiết bị trong đó không kết nối ra mạng thật.

## 6. Yêu cầu chức năng

Mỗi yêu cầu FR được viết để kiểm thử được; cột "Từ" nối về mã tính năng F-xx trong PRD.

### 6.1 Xác thực và phân quyền

| Mã | Yêu cầu | Từ |
| --- | --- | --- |
| FR-01 | Hệ thống cho phép đăng nhập bằng username/password; mật khẩu lưu dạng hash. | F-01 |
| FR-02 | Sai mật khẩu 5 lần liên tiếp thì khóa tài khoản 5 phút. | F-01 |
| FR-03 | Mỗi trang và API kiểm tra vai trò; truy cập sai quyền trả HTTP 403. | F-01 |

### 6.2 Kiểm kê thiết bị

| Mã | Yêu cầu | Từ |
| --- | --- | --- |
| FR-10 | Admin thêm thiết bị với: tên (bắt buộc, duy nhất), IP (bắt buộc, IPv4 hợp lệ, duy nhất), loại, nhóm, MAC, vị trí, hãng, ghi chú. | F-02 |
| FR-11 | Mỗi loại có thuộc tính riêng: Router (số interface), Switch (số port, VLAN), Server (OS, dịch vụ), Printer (model). | F-02 |
| FR-12 | Khi tạo thiết bị, hệ thống tự gắn sensor mặc định theo loại (Router/Switch: Ping + SSH port; Server: Ping + HTTP). | F-02, F-07 |
| FR-13 | Xóa thiết bị phải xác nhận; xóa kèm sensor nhưng giữ lịch sử cảnh báo. | F-02 |
| FR-14 | Nhóm lồng nhau không giới hạn cấp; không cho tạo vòng (nhóm là con của chính nó). | F-03 |
| FR-15 | Trạng thái nhóm = trạng thái xấu nhất của các phần tử con (DOWN > WARNING > UP). | F-03 |
| FR-16 | Tìm kiếm theo tên/IP/MAC (khớp một phần), lọc theo loại/nhóm/trạng thái, phân trang 20 dòng. | F-04 |
| FR-17 | Nhập CSV: kiểm tra từng dòng, báo dòng lỗi, chỉ nhập dòng hợp lệ. Xuất CSV theo bộ lọc hiện tại. | F-05 |
| FR-18 | Quét mạng nhận CIDR tối đa /22 (1.024 địa chỉ), ping song song, trả về IP sống, hostname (reverse DNS), port mở trong danh sách 22/23/80/443/161. | F-06 |
| FR-19 | Kết quả quét đánh dấu IP đã có trong kho; Admin chọn dòng để thêm hàng loạt. | F-06 |

### 6.3 Giám sát

| Mã | Yêu cầu | Từ |
| --- | --- | --- |
| FR-30 | Sensor có: tên, loại, chu kỳ (10–3.600 giây, mặc định 30), timeout, ngưỡng WARNING, số lần lỗi liên tiếp trước khi DOWN (mặc định 3). | F-07, F-10 |
| FR-31 | PingSensor đo RTT (ms) và tỉ lệ mất gói; WARNING khi RTT > ngưỡng hoặc mất gói > 20%. | F-07 |
| FR-32 | PortSensor mở kết nối TCP tới port cấu hình; DOWN khi không kết nối được trong timeout. | F-07 |
| FR-33 | HttpSensor gửi GET tới URL; DOWN khi mã trả về khác 2xx/3xx; tùy chọn kiểm tra nội dung có chứa chuỗi. | F-07 |
| FR-34 | DnsSensor phân giải tên miền; SnmpSensor đọc sysUpTime, CPU, trạng thái interface qua OID cấu hình. | F-08 |
| FR-35 | Scheduler chạy mỗi sensor đúng chu kỳ, nhiều sensor song song, một sensor lỗi không làm dừng sensor khác. | F-09 |
| FR-36 | Admin tạm dừng/tiếp tục từng sensor, cả thiết bị hoặc cả nhóm; khi tạm dừng trạng thái là PAUSED và không sinh cảnh báo. | F-09 |
| FR-37 | Mỗi lần check lưu CheckResult (thời điểm, trạng thái, giá trị, thông điệp); giữ 30 ngày rồi tự xóa. | F-14 |
| FR-38 | Khi trạng thái thay đổi, server đẩy sự kiện qua WebSocket; dashboard cập nhật trong ≤ 2 giây. | F-11 |

### 6.4 Cảnh báo

| Mã | Yêu cầu | Từ |
| --- | --- | --- |
| FR-40 | Chỉ tạo Alert khi trạng thái đổi (UP→WARNING, →DOWN, →UP), không tạo lại khi trạng thái giữ nguyên. | F-12 |
| FR-41 | Alert có mức (INFO/WARNING/CRITICAL), trạng thái (OPEN/ACKNOWLEDGED/RESOLVED), người xác nhận, ghi chú. | F-12 |
| FR-42 | Khi sensor trở lại UP, Alert tương ứng chuyển RESOLVED tự động. | F-12 |
| FR-43 | Mỗi kênh thông báo (web, log, email, Telegram) bật/tắt độc lập và có nút "Gửi thử". Kênh lỗi được ghi log, không ảnh hưởng kênh khác. | F-13 |

### 6.5 Báo cáo

| Mã | Yêu cầu | Từ |
| --- | --- | --- |
| FR-50 | Uptime % = thời gian UP / (tổng thời gian − thời gian PAUSED) trong khoảng đã chọn. | F-14 |
| FR-51 | Biểu đồ độ trễ theo thời gian cho 24 giờ, 7 ngày, 30 ngày. | F-14 |
| FR-52 | Báo cáo theo nhóm gồm: số thiết bị, uptime trung bình, số lần DOWN, tổng thời gian DOWN, top 5 thiết bị kém nhất; xuất CSV và PDF. | F-15 |

### 6.6 Cấu hình từ xa

| Mã | Yêu cầu | Từ |
| --- | --- | --- |
| FR-60 | Mỗi thiết bị lưu: giao thức (SSH/Telnet), port, username, password (mã hoá Fernet), hãng/driver (VyOS, MikroTik, Cisco IOS). | F-16 |
| FR-61 | Nút "Kiểm tra kết nối" báo thành công hoặc lỗi rõ ràng (timeout, sai mật khẩu, từ chối kết nối). | F-16 |
| FR-62 | Xem running-config, bảng interface (tên, IP, trạng thái), routing table; driver dịch sang lệnh phù hợp với hãng. | F-17 |
| FR-63 | Backup thủ công hoặc theo lịch (mặc định 1 lần/ngày); giữ 10 bản gần nhất; so sánh 2 bản dạng diff tô màu. | F-18 |
| FR-64 | Thao tác có sẵn: đổi hostname, đặt IP interface, bật/tắt interface. Trước khi gửi phải hiển thị lệnh sẽ chạy để xác nhận. | F-19 |
| FR-65 | Mỗi thao tác được lưu vào lịch sử cấu hình kèm lệnh ngược; Admin hoàn tác được từng thao tác theo thứ tự ngược. | F-19 |
| FR-66 | Terminal web: phiên SSH/Telnet tương tác qua WebSocket, tự đóng sau 10 phút không hoạt động, ghi log lệnh đã gõ. | F-20 |

### 6.7 Hệ thống

| Mã | Yêu cầu | Từ |
| --- | --- | --- |
| FR-70 | Ghi audit log cho mọi thao tác thêm/sửa/xóa, đăng nhập và lệnh cấu hình: người dùng, thời điểm, hành động, đối tượng. | F-21 |
| FR-71 | Admin quản lý tài khoản: tạo, khóa, đổi vai trò, đặt lại mật khẩu. | F-01 |

## 7. Phi chức năng, use case, dữ liệu và thiết kế lớp

Thiết kế lớp là phần cốt lõi của báo cáo OOP: mỗi pattern dưới đây giải quyết một yêu cầu cụ thể ở mục 6, không dùng cho có.

### 7.1 Yêu cầu phi chức năng

| Mã | Nhóm | Yêu cầu |
| --- | --- | --- |
| NFR-01 | Hiệu năng | 100 thiết bị / 300 sensor chu kỳ 30 giây, CPU trung bình < 30% trên laptop 4 nhân |
| NFR-02 | Hiệu năng | Trang danh sách và dashboard tải < 1 giây với 100 thiết bị |
| NFR-03 | Bảo mật | Mật khẩu người dùng hash (PBKDF2/bcrypt); mật khẩu thiết bị mã hoá Fernet; khóa trong `.env` |
| NFR-04 | Bảo mật | Form có CSRF token; mật khẩu không bao giờ trả về trong API hay ghi vào log |
| NFR-05 | Tin cậy | Khởi động lại ứng dụng không mất dữ liệu; scheduler tự chạy lại các sensor đang bật |
| NFR-06 | Mở rộng | Thêm loại sensor, loại thiết bị, kênh thông báo hoặc driver hãng mới chỉ cần thêm 1 class + đăng ký |
| NFR-07 | Bảo trì | Code theo PEP 8, có type hint; tầng domain không import Flask/SQLAlchemy; test domain ≥ 70% |
| NFR-08 | Khả dụng | Giao diện tiếng Việt, hiển thị tốt từ 1280 px trở lên |

### 7.2 Use case chính

| Use case | Tác nhân | Luồng chính | Ngoại lệ |
| --- | --- | --- | --- |
| UC-01 Thêm thiết bị | Admin | Mở form → chọn loại → nhập thông tin → Lưu → hệ thống tạo thiết bị + sensor mặc định → sensor bắt đầu chạy | IP trùng hoặc sai định dạng → báo lỗi tại trường |
| UC-02 Quét mạng | Admin | Nhập CIDR → Bắt đầu → xem tiến trình → chọn kết quả → Thêm | CIDR lớn hơn /22 → từ chối |
| UC-03 Giám sát tự động | Scheduler | Đến chu kỳ → sensor.check() → lưu kết quả → nếu đổi trạng thái thì báo AlertManager và đẩy WebSocket | Check ném exception → trạng thái UNKNOWN, ghi log |
| UC-04 Xác nhận cảnh báo | Operator | Mở Cảnh báo → chọn → Xác nhận + ghi chú | Cảnh báo đã RESOLVED → không cho xác nhận |
| UC-05 Backup cấu hình | Admin / lịch | Kết nối → driver lấy config → lưu bản mới → ngắt kết nối | Kết nối lỗi → ghi log, tạo cảnh báo WARNING |
| UC-06 Thay đổi cấu hình | Admin | Chọn thao tác → xem trước lệnh → Xác nhận → backup tự động → thực thi → lưu lịch sử | Thiết bị trả lỗi cú pháp → không lưu lịch sử, hiển thị output |
| UC-07 Hoàn tác | Admin | Chọn dòng lịch sử → Hoàn tác → gửi lệnh ngược | Còn thao tác mới hơn chưa hoàn tác → yêu cầu hoàn tác theo thứ tự |
| UC-08 Xuất báo cáo | Tất cả | Chọn khoảng thời gian + nhóm → Xem → Xuất CSV/PDF | Không có dữ liệu → báo rỗng |

### 7.3 Mô hình dữ liệu (bảng chính)

| Bảng | Trường chính | Quan hệ |
| --- | --- | --- |
| `users` | id, username, password\_hash, role, is\_locked |  |
| `groups` | id, name, parent\_id | tự tham chiếu (cây) |
| `devices` | id, name, ip, mac, device\_type, vendor, location, group\_id, extra (JSON thuộc tính riêng theo loại) | N–1 groups |
| `credentials` | id, device\_id, protocol, port, username, password\_enc | 1–1 devices |
| `sensors` | id, device\_id, sensor\_type, interval, timeout, params (JSON), status, paused | N–1 devices |
| `check_results` | id, sensor\_id, ts, status, value, message | N–1 sensors |
| `alerts` | id, sensor\_id, level, state, opened\_at, ack\_by, ack\_note, resolved\_at | N–1 sensors |
| `config_backups` | id, device\_id, ts, content | N–1 devices |
| `config_changes` | id, device\_id, user\_id, command\_type, params, forward\_cmds, undo\_cmds, ts, undone | N–1 devices |
| `audit_logs` | id, user\_id, action, target, ts | N–1 users |

### 7.4 Thiết kế lớp và 4 tính chất OOP

| Tính chất | Thể hiện ở đâu |
| --- | --- |
| Trừu tượng | `Device`, `Sensor`, `Notifier`, `Connection`, `DeviceDriver`, `ConfigCommand`, `Repository` là lớp trừu tượng (`abc.ABC`) |
| Kế thừa | `Router`, `Switch`, `Server`, `PC`, `Printer` ← `Device`; `PingSensor`, `PortSensor`, `HttpSensor`, `DnsSensor`, `SnmpSensor` ← `Sensor` |
| Đa hình | Scheduler gọi `sensor.check()` mà không biết loại; `driver.get_running_config()` trả kết quả đúng cho từng hãng; `device.default_sensors()` khác nhau theo loại |
| Đóng gói | `ip`, `status`, `threshold` là thuộc tính private + `@property` có kiểm tra (IP sai định dạng → `ValueError`); status chỉ đổi qua `_update_status()` để luôn phát sự kiện |

### 7.5 Design pattern

| Pattern | Lớp | Giải quyết yêu cầu |
| --- | --- | --- |
| Composite | `NetworkNode` ← `Group`, `Device` | FR-14, FR-15: nhóm lồng nhau, tính trạng thái tổng bằng đệ quy |
| Observer | `Sensor` (subject) → `AlertManager`, `WebSocketPublisher`, `ResultRecorder` | FR-38, FR-40: một lần đổi trạng thái, nhiều nơi phản ứng |
| Factory + Registry | `SensorFactory`, `DeviceFactory`, `DriverFactory` | NFR-06: thêm loại mới bằng decorator `@SensorFactory.register("ping")` |
| Strategy | `Connection` ← `SSHConnection`, `TelnetConnection`, `FakeConnection` | FR-60: đổi giao thức không sửa driver; Fake dùng cho test |
| Adapter | `DeviceDriver` ← `VyOSDriver`, `MikroTikDriver`, `CiscoIOSDriver` | FR-62: cùng giao diện, lệnh khác nhau theo hãng |
| Command | `ConfigCommand` ← `SetHostname`, `SetInterfaceIP`, `ToggleInterface`; `CommandHistory` | FR-64, FR-65: execute/undo, rollback theo thứ tự ngược |
| Template Method | `Sensor.run()` = đo giờ → `check()` → so ngưỡng → cập nhật trạng thái | FR-30: lớp con chỉ viết phần đo |
| Repository | `DeviceRepository` ← `SqlDeviceRepository`, `InMemoryDeviceRepository` | NFR-07: tách domain khỏi CSDL, test không cần DB |
| Singleton | `MonitorScheduler` | FR-35: chỉ một bộ lập lịch trong ứng dụng |
| Facade | `NetMonService` (gồm Inventory, Monitor, Alert, Config service) | Route Flask chỉ gọi một đầu mối |

Khung lớp Sensor minh họa Template Method + Observer:

```python
class Sensor(ABC):
    def __init__(self, name: str, interval: int = 30, threshold: float | None = None):
        self._name, self._interval, self._threshold = name, interval, threshold
        self._status = Status.UNKNOWN
        self._observers: list[SensorObserver] = []

    def run(self) -> CheckResult:          # Template Method
        result = self.check()
        result = self._apply_threshold(result)
        self._update_status(result)
        return result

    @abstractmethod
    def check(self) -> CheckResult: ...    # lớp con tự cài đặt

    def _update_status(self, result: CheckResult) -> None:
        if result.status != self._status:
            old, self._status = self._status, result.status
            for o in self._observers:      # Observer
                o.on_status_changed(self, old, result)
```

### 7.6 REST API chính

API dùng JSON, xác thực bằng session đăng nhập; trang web gọi các API này qua `fetch`.

| Phương thức | Đường dẫn | Chức năng | Quyền |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | Đăng nhập | Tất cả |
| GET / POST | `/api/devices` | Danh sách (có `?q=&type=&group=&status=&page=`) / thêm thiết bị | Xem: tất cả; thêm: Admin |
| GET / PUT / DELETE | `/api/devices/<id>` | Chi tiết / sửa / xóa | Admin cho PUT, DELETE |
| GET / POST | `/api/groups` | Cây nhóm / thêm nhóm | Admin cho POST |
| POST | `/api/devices/<id>/sensors` | Gắn sensor | Admin |
| PATCH | `/api/sensors/<id>` | Sửa tham số, tạm dừng/tiếp tục | Admin |
| GET | `/api/sensors/<id>/results?from=&to=` | Lịch sử check | Tất cả |
| POST | `/api/discovery` | Bắt đầu quét, trả job\_id | Admin |
| GET | `/api/discovery/<job_id>` | Tiến trình và kết quả | Admin |
| GET | `/api/alerts?state=&level=` | Danh sách cảnh báo | Tất cả |
| POST | `/api/alerts/<id>/ack` | Xác nhận cảnh báo | Admin, Operator |
| GET | `/api/reports/uptime?from=&to=&group=&format=csv\|pdf` | Báo cáo uptime | Tất cả |
| POST | `/api/devices/<id>/connection-test` | Kiểm tra SSH/Telnet | Admin |
| GET | `/api/devices/<id>/config/running` | Lấy running-config | Admin, Operator |
| POST / GET | `/api/devices/<id>/backups` | Tạo / liệt kê bản backup | Admin |
| GET | `/api/devices/<id>/backups/diff?a=&b=` | So sánh 2 bản | Admin |
| POST | `/api/devices/<id>/commands` | Thực thi thao tác cấu hình (`preview=true` để xem trước lệnh) | Admin |
| POST | `/api/commands/<id>/undo` | Hoàn tác | Admin |
| WS | `/ws/status`, `/ws/terminal/<device_id>` | Đẩy trạng thái; terminal web | Tất cả; Admin |

## 8. Ràng buộc, kiểm thử và truy vết

Mỗi yêu cầu Must có ít nhất một ca kiểm thử; nghiệm thu khi toàn bộ ca dưới đây chạy đạt trên lab ảo.

**Ràng buộc**

- Ngôn ngữ Python 3.11+, áp dụng lập trình hướng đối tượng cho toàn bộ tầng domain và service.
- Chỉ dùng thư viện mã nguồn mở; image thiết bị ảo miễn phí (VyOS, MikroTik CHR, FRR, Open vSwitch).
- Chạy trên 1 máy Windows 10+/Ubuntu 22.04+, RAM ≥ 8 GB (bao gồm lab).
- Telnet chỉ dùng trong lab vì gửi mật khẩu dạng rõ.

**Ca kiểm thử nghiệm thu**

| Mã | Kịch bản | Kết quả mong đợi | Yêu cầu |
| --- | --- | --- | --- |
| TC-01 | Đăng nhập sai 5 lần | Tài khoản bị khóa 5 phút | FR-02 |
| TC-02 | Viewer gọi `DELETE /api/devices/1` | HTTP 403, thiết bị còn nguyên | FR-03 |
| TC-03 | Thêm thiết bị IP `192.168.1.300` | Báo lỗi IP không hợp lệ, không lưu | FR-10 |
| TC-04 | Thêm Server mới | Tự có PingSensor + HttpSensor, chạy trong 30 giây | FR-12 |
| TC-05 | Nhóm A chứa 1 thiết bị DOWN, 3 UP | Nhóm A hiển thị DOWN | FR-15 |
| TC-06 | Quét 192.168.100.0/24 trong lab | Trả đủ 4 thiết bị lab, đánh dấu thiết bị đã có | FR-18, FR-19 |
| TC-07 | Tắt router R1 trong lab | Sensor DOWN sau 3 lần lỗi, dashboard đỏ ≤ 2 giây sau, có 1 Alert và 1 tin Telegram | FR-31, FR-38, FR-40, FR-43 |
| TC-08 | Giữ R1 DOWN thêm 5 chu kỳ | Không phát sinh Alert mới | FR-40 |
| TC-09 | Bật lại R1 | Sensor UP, Alert tự RESOLVED | FR-42 |
| TC-10 | Sensor HTTP trỏ tới URL trả 500 | Trạng thái DOWN | FR-33 |
| TC-11 | Tạm dừng nhóm rồi tắt thiết bị trong nhóm | Trạng thái PAUSED, không có Alert | FR-36 |
| TC-12 | Backup R1, đổi hostname, backup lại, diff | Diff chỉ khác dòng hostname | FR-63, FR-64 |
| TC-13 | Tắt eth1 của R1 rồi Hoàn tác | eth1 bật lại, lịch sử ghi undone | FR-65 |
| TC-14 | Kiểm tra kết nối với mật khẩu sai | Báo "sai thông tin đăng nhập", không treo giao diện | FR-61 |
| TC-15 | Thêm class `IcmpJitterSensor` + đăng ký Factory | Sensor mới xuất hiện trong form, không sửa file cũ | NFR-06 |
| TC-16 | Mở DB / log tìm mật khẩu thiết bị | Chỉ thấy chuỗi đã mã hoá | NFR-03, NFR-04 |

**Ma trận truy vết (tóm tắt)**

| Module PRD | Tính năng | Yêu cầu SRS | Ca kiểm thử |
| --- | --- | --- | --- |
| Xác thực | F-01 | FR-01 → FR-03, FR-71 | TC-01, TC-02 |
| Kiểm kê | F-02 → F-06 | FR-10 → FR-19 | TC-03 → TC-06 |
| Giám sát | F-07 → F-11 | FR-30 → FR-38 | TC-07, TC-10, TC-11 |
| Cảnh báo | F-12, F-13 | FR-40 → FR-43 | TC-07 → TC-09 |
| Báo cáo | F-14, F-15 | FR-37, FR-50 → FR-52 | (kiểm tra thủ công số liệu uptime) |
| Cấu hình từ xa | F-16 → F-20 | FR-60 → FR-66 | TC-12 → TC-14 |
| Hệ thống | F-21 | FR-70 | (kiểm tra audit log sau TC-12) |
| Phi chức năng | — | NFR-01 → NFR-08 | TC-15, TC-16 |
