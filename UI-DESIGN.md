# NetMon – Tài liệu thiết kế giao diện (UI Design Spec)

> Tài liệu thứ 3, đi kèm **PRD** và **SRS** của NetMon. Mã F-xx / FR-xx tham chiếu sang hai tài liệu đó.
> Đối tượng đọc: lập trình viên hoặc coding agent dựng phần web (Flask + Jinja2 + Bootstrap 5).
> Phiên bản: 2026-11-22

---

## 1. Nguyên tắc thiết kế

Giao diện **lấy bố cục và cách hiển thị của PRTG Network Monitor làm mẫu**: nền trắng/xám, bảng dày đặc thông tin, màu sắc **chỉ dùng để báo trạng thái**. Chỉ học bố cục, **không** dùng logo, tên hay hình ảnh thương hiệu PRTG.

1. **Trạng thái là thứ duy nhất có màu.** Mọi thứ khác (nền, viền, chữ, nút) đều là trắng, xám hoặc xanh dương trung tính. Người dùng liếc qua là thấy ngay chỗ đỏ.
2. **Mật độ cao, ít trang trí.** Không gradient, không đổ bóng, không bo góc lớn, không ảnh minh họa, không animation trừ spinner tải.
3. **Cây Group → Device → Sensor là trung tâm.** Giống PRTG, trang chính là cây thiết bị; sensor hiện thành các ô vuông nhỏ có màu ngay cạnh thiết bị.
4. **Mọi thứ cách tối đa 2 cú click.** Menu ngang trên cùng, breadcrumb dưới menu, tab trong trang chi tiết.
5. **Nhất quán.** Cùng một loại thông tin luôn hiển thị cùng một kiểu (badge trạng thái, định dạng thời gian, định dạng số).

---

## 2. Design tokens

Khai báo trong `static/css/netmon.css` bằng CSS variables, ghi đè lên Bootstrap.

### 2.1 Màu nền và chữ

| Token | Giá trị | Dùng cho |
|---|---|---|
| `--nm-bg` | `#F4F5F7` | Nền trang |
| `--nm-surface` | `#FFFFFF` | Nền panel, bảng, form |
| `--nm-header` | `#2B3A4A` | Thanh header trên cùng (xanh than) |
| `--nm-header-text` | `#FFFFFF` | Chữ trên header |
| `--nm-menu-bg` | `#FFFFFF` | Thanh menu chính |
| `--nm-border` | `#D9DCE1` | Viền bảng, panel, input |
| `--nm-row-alt` | `#FAFBFC` | Dòng chẵn của bảng |
| `--nm-row-hover` | `#EEF3F8` | Hover dòng bảng |
| `--nm-text` | `#1F2933` | Chữ chính |
| `--nm-text-muted` | `#6B7785` | Chữ phụ, nhãn, thời gian |
| `--nm-link` | `#1F6FB2` | Link, nút chính (primary) |
| `--nm-focus` | `#1F6FB2` | Viền focus của input (1px) |

### 2.2 Màu trạng thái (giống PRTG)

| Trạng thái | Token | Nền | Chữ trên nền |
|---|---|---|---|
| UP | `--nm-up` | `#5CB85C` | trắng |
| WARNING | `--nm-warning` | `#F0C419` | `#1F2933` (đen) |
| DOWN | `--nm-down` | `#D9534F` | trắng |
| DOWN (đã xác nhận) | `--nm-down-ack` | `#E89A97` | `#1F2933` |
| PAUSED | `--nm-paused` | `#5B8DD6` | trắng |
| UNKNOWN | `--nm-unknown` | `#A0A7B0` | trắng |

Mức cảnh báo dùng lại màu trên: CRITICAL = `--nm-down`, WARNING = `--nm-warning`, INFO = `--nm-paused`.

**Không bao giờ chỉ dùng màu để truyền thông tin**: badge luôn kèm chữ (`UP`, `DOWN`…) hoặc icon, tooltip có tên trạng thái.

### 2.3 Chữ, khoảng cách, đường viền

| Thuộc tính | Giá trị |
|---|---|
| Font | `-apple-system, "Segoe UI", Roboto, Arial, sans-serif` |
| Cỡ chữ gốc | 13px (bảng, form); tiêu đề trang 18px/600; tiêu đề panel 14px/600 |
| Số liệu (IP, ms, %) | `font-variant-numeric: tabular-nums`; IP và MAC dùng font monospace 12px |
| Khoảng cách | bội số của 4px: 4, 8, 12, 16, 24 |
| Chiều cao dòng bảng | 30px |
| Chiều cao input/nút | 28px |
| Bo góc | 2px (input, nút, panel); 0 cho bảng |
| Viền | 1px `--nm-border` |
| Đổ bóng | không dùng |
| Icon | Bootstrap Icons, 14px, màu `--nm-text-muted` |

### 2.4 Định dạng dữ liệu

- Thời gian: `22/11/2026 14:05:31`; thời gian tương đối trong bảng: `2 phút trước` (tooltip là thời gian đầy đủ).
- Độ trễ: `12 ms`; uptime: `99,82 %` (dấu phẩy thập phân theo tiếng Việt).
- Khoảng thời gian: `3 ngày 4 giờ 12 phút`.
- Ô không có dữ liệu: `–` màu `--nm-text-muted`.

---

## 3. Khung trang (layout shell)

Mọi trang (trừ Đăng nhập) dùng chung `templates/base.html`.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ NetMon        [ Tìm thiết bị, IP... ]     ■3 DOWN ■5 WARN ■42 UP ■2 PAUSED  admin ▾ │  ← Header 40px, nền --nm-header
├──────────────────────────────────────────────────────────────────────────────┤
│ Trang chủ │ Thiết bị │ Sensor │ Cảnh báo (3) │ Quét mạng │ Báo cáo │ Nhật ký │ Cài đặt │  ← Menu chính 36px, nền trắng
├──────────────────────────────────────────────────────────────────────────────┤
│ Trang chủ › Thiết bị › Tầng 2 › Router R1                                    │  ← Breadcrumb 28px, chữ muted
├──────────────────────────────────────────────────────────────────────────────┤
│  Tiêu đề trang                                            [Nút hành động]   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Nội dung                                                            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────────────┤
│ NetMon v1.0 · Cập nhật lần cuối: 14:05:31 · ● Đã kết nối realtime            │  ← Footer 24px
└──────────────────────────────────────────────────────────────────────────────┘
```

**Header**
- Trái: chữ "NetMon" (16px/600, trắng), click về Trang chủ. Không logo hình.
- Giữa: ô tìm kiếm nhanh (rộng 280px). Gõ ≥ 2 ký tự → dropdown gợi ý tối đa 8 thiết bị (tên + IP + badge trạng thái). Enter → `/devices?q=...`.
- Phải: **thanh tổng trạng thái** kiểu PRTG: các ô vuông nhỏ có màu kèm số, chỉ hiện ô có số > 0; click ô → danh sách sensor lọc theo trạng thái đó. Cập nhật qua WebSocket.
- Ngoài cùng bên phải: tên người dùng + vai trò, dropdown gồm "Đổi mật khẩu", "Đăng xuất".

**Menu chính**
- Mục đang chọn: chữ `--nm-link`, gạch chân 2px. Không icon.
- "Cảnh báo (3)": số trong ngoặc = số cảnh báo OPEN, chữ đỏ khi > 0.
- Ẩn mục người dùng không có quyền: Viewer không thấy "Quét mạng", "Cài đặt"; Operator không thấy "Cài đặt".

**Vùng nội dung**: rộng tối đa 1440px, padding 16px, nền `--nm-bg`; panel bên trong nền trắng, viền 1px.

**Footer**: chấm tròn xanh "Đã kết nối realtime" / xám "Mất kết nối – đang thử lại…" theo trạng thái WebSocket.

---

## 4. Thành phần dùng chung (components)

Mỗi component là một Jinja macro trong `templates/components/`.

### 4.1 Badge trạng thái — `status_badge(status)`
Hình chữ nhật 2px bo góc, cao 18px, padding 0 6px, chữ in hoa 11px/600, màu theo bảng 2.2.
```
[ UP ]  [ WARNING ]  [ DOWN ]  [ PAUSED ]  [ UNKNOWN ]
```

### 4.2 Ô sensor — `sensor_tile(sensor)` (đặc trưng PRTG)
Ô chữ nhật nền màu trạng thái, rộng 120px, cao 36px, 2 dòng chữ:
```
┌──────────────┐
│ Ping         │   ← tên sensor, 11px/600
│ 12 ms        │   ← giá trị cuối, 12px
└──────────────┘
```
- Hover: tooltip gồm loại sensor, lần check cuối, thông điệp.
- Click: mở trang chi tiết sensor.
- PAUSED: thêm icon ⏸ nhỏ. DOWN đã xác nhận: màu `--nm-down-ack`.

### 4.3 Chấm trạng thái — `status_dot(status)`
Hình vuông 10×10px (không tròn, giống PRTG), dùng trong cây và bảng chật chỗ.

### 4.4 Bảng dữ liệu — `data_table(...)`
- Header nền `#EEF0F3`, chữ 12px/600, có mũi tên sắp xếp ▲▼ khi click.
- Dòng 30px, kẻ ngang 1px, dòng chẵn `--nm-row-alt`, hover `--nm-row-hover`.
- Cột đầu: checkbox (nếu có thao tác hàng loạt). Cột cuối: menu `⋯` (Sửa, Tạm dừng, Xóa).
- Thanh công cụ trên bảng: ô lọc nhanh, dropdown bộ lọc, nút hành động bên phải.
- Phân trang dưới bảng: `‹ 1 2 3 … 9 ›` + "Hiển thị 1–20 / 173".
- Khi chọn ≥ 1 dòng: thanh hành động hàng loạt thay thế thanh công cụ ("Đã chọn 3 · Tạm dừng · Tiếp tục · Xóa").

### 4.5 Panel — `panel(title, actions)`
Nền trắng, viền 1px, tiêu đề 14px/600 cao 36px với đường kẻ dưới, nút nhỏ bên phải tiêu đề.

### 4.6 Nút
| Loại | Kiểu |
|---|---|
| Chính | nền `--nm-link`, chữ trắng |
| Phụ | nền trắng, viền `--nm-border`, chữ `--nm-text` |
| Nguy hiểm | nền trắng, viền và chữ `--nm-down`; chỉ cho Xóa, Tắt interface |
| Liên kết | không viền, chữ `--nm-link` |
Mỗi vùng chỉ có **tối đa 1 nút chính**.

### 4.7 Form
- Nhãn bên trái (rộng 160px, căn phải), input bên phải — bố cục 2 cột giống trang cài đặt PRTG.
- Trường bắt buộc: dấu `*` đỏ sau nhãn.
- Lỗi: viền input đỏ + dòng chữ đỏ 12px dưới input; lỗi chung ở hộp đỏ nhạt đầu form.
- Nút "Lưu" (chính) và "Hủy" (liên kết) ở cuối form, căn trái theo cột input.

### 4.8 Hộp thoại xác nhận — `confirm_modal`
Rộng 420px, tiêu đề, 1–2 câu mô tả hậu quả, ô xem trước (nếu là lệnh cấu hình), nút "Hủy" + nút hành động (nguy hiểm nếu là xóa/tắt).

### 4.9 Thông báo nổi (toast)
Góc dưới phải, 320px, tự ẩn sau 5 giây; viền trái 4px theo màu trạng thái. Dùng khi: lưu thành công, thiết bị chuyển trạng thái (chỉ DOWN và khôi phục UP), lỗi kết nối.

### 4.10 Trạng thái rỗng, đang tải, lỗi
- Rỗng: 1 dòng chữ muted giữa panel + 1 nút hành động. VD: "Chưa có thiết bị nào. [Thêm thiết bị] [Quét mạng]".
- Đang tải: spinner 16px + "Đang tải…". Bảng giữ chiều cao cũ, không nhảy layout.
- Lỗi: hộp viền đỏ "Không tải được dữ liệu. [Thử lại]".

---

## 5. Thiết kế từng trang

### 5.1 Đăng nhập — `/login` (F-01)
```
                 ┌─────────────────────────────┐
                 │ NetMon                      │
                 │ Đăng nhập hệ thống          │
                 │                             │
                 │ Tên đăng nhập [___________] │
                 │ Mật khẩu      [___________] │
                 │ [ Đăng nhập ]               │
                 │                             │
                 │ ⚠ Sai tên đăng nhập hoặc... │
                 └─────────────────────────────┘
```
Panel 360px giữa màn hình, nền trang `--nm-bg`. Khi bị khóa: "Tài khoản tạm khóa, thử lại sau 4 phút 12 giây".

### 5.2 Trang chủ / Dashboard — `/` (F-11)
```
┌─ Tổng quan ───────────────────────────────────────────────────────────────┐
│ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                    │
│ │   3    │ │   5    │ │  42    │ │   2    │ │  52    │                    │
│ │ DOWN   │ │WARNING │ │  UP    │ │ PAUSED │ │ Tổng   │                    │
│ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘                    │
└───────────────────────────────────────────────────────────────────────────┘
┌─ Cảnh báo đang mở ──────────────────────┐ ┌─ Độ trễ cao nhất ───────────────┐
│ ■ 14:02  R1 · Ping          DOWN  [Xác nhận] │ │ 1. SRV-WEB   HTTP   480 ms ■   │
│ ■ 13:58  SW-T2 · Port 22    DOWN  [Xác nhận] │ │ 2. R2        Ping   210 ms ■   │
│ ■ 13:40  SRV-DB · Ping      WARN  [Xác nhận] │ │ ...                            │
│ Xem tất cả ›                            │ └─────────────────────────────────┘
└─────────────────────────────────────────┘
┌─ Thiết bị theo nhóm ──────────────────────────────────────────────────────┐
│ ▾ ■ Tòa A                                                                 │
│   ▾ ■ Tầng 2                                                              │
│       ■ Router R1   192.168.100.1   [Ping ✕] [SSH 22 ✕]                   │
│       ■ SW-T2       192.168.100.2   [Ping 3ms] [SSH 22 ✕]                 │
│   ▸ ■ Tầng 3   (12 thiết bị)                                              │
└───────────────────────────────────────────────────────────────────────────┘
```
- Hàng ô tổng: 5 ô 120×64px; ô có số > 0 mang màu trạng thái, ô = 0 nền trắng chữ muted. Click → danh sách sensor đã lọc.
- Cảnh báo đang mở: 10 dòng mới nhất, nút "Xác nhận" (ẩn với Viewer).
- Độ trễ cao nhất: top 5 sensor Ping/HTTP.
- Cây thiết bị: giống trang 5.3 nhưng chỉ đọc, mặc định mở các nhóm đang có DOWN.
- Mọi khối cập nhật qua WebSocket, không reload trang; ô vừa đổi màu nháy viền 1 lần (300ms).

### 5.3 Thiết bị (cây) — `/devices` (F-02, F-03, F-04)
Trang chính kiểu "Devices" của PRTG, có 2 chế độ xem chuyển bằng nút gạt `[Cây | Bảng]`.

**Chế độ Cây (mặc định)**
```
[ Lọc: tên/IP ___ ] [Loại ▾] [Trạng thái ▾]                 [+ Thêm thiết bị] [Nhập CSV] [Xuất CSV]
────────────────────────────────────────────────────────────────────────────────────────
▾ ■ Tòa A                                              3 DOWN · 1 WARN · 20 UP        ⋯
  ▾ ■ Tầng 2                                           2 DOWN · 6 UP                  ⋯
      ■ Router R1  ·  192.168.100.1  ·  VyOS
        [Ping   ] [SSH 22 ] [SNMP CPU]                                                ⋯
        [✕ DOWN ] [✕ DOWN ] [– UNK  ]
      ■ SW-T2  ·  192.168.100.2  ·  Open vSwitch
        [Ping   ] [SSH 22 ]                                                           ⋯
        [3 ms   ] [OK     ]
  ▸ ■ Tầng 3                                           12 UP                          ⋯
```
- Dòng nhóm: chấm trạng thái tổng + tên (600) + tóm tắt số lượng bên phải.
- Dòng thiết bị: chấm + tên (link sang chi tiết) + IP (monospace) + hãng; dưới là hàng ô sensor (4.2), tự xuống dòng.
- Menu `⋯` của nhóm: Thêm nhóm con, Thêm thiết bị vào đây, Đổi tên, Tạm dừng tất cả, Xóa.
- Menu `⋯` của thiết bị: Sửa, Thêm sensor, Tạm dừng, Xóa.
- Kéo thả thiết bị/nhóm sang nhóm khác (Admin) → hộp xác nhận "Chuyển R1 sang Tầng 3?".

**Chế độ Bảng**: cột `☐ | Trạng thái | Tên | IP | Loại | Nhóm | Hãng | Sensor (■■■) | Lần check cuối | ⋯`, sắp xếp được theo mọi cột, 20 dòng/trang.

### 5.4 Chi tiết thiết bị — `/devices/<id>` (F-07, F-14, F-17 → F-20)
```
■ Router R1                           [DOWN]          [Tạm dừng] [Sửa] [⋯]
192.168.100.1 · VyOS · Tầng 2 · Lần check cuối 14:05:31
┌──────────┬─────────┬──────────┬──────────┬──────────┐
│ Tổng quan│ Lịch sử │ Cấu hình │ Terminal │ Nhật ký  │
└──────────┴─────────┴──────────┴──────────┴──────────┘
```
Tab Cấu hình và Terminal chỉ hiện với Admin (Operator thấy tab Cấu hình ở chế độ chỉ xem).

**Tab Tổng quan**
- Panel trái (40%): bảng thuộc tính 2 cột (Nhãn | Giá trị): Tên, IP, MAC, Loại, Hãng, Nhóm, Vị trí, thuộc tính riêng theo loại (VD Switch: Số port, VLAN), Giao thức quản trị, Ghi chú.
- Panel phải (60%): **bảng sensor** — `Trạng thái | Tên | Loại | Giá trị cuối | Chu kỳ | Lần check cuối | Thông điệp | ⋯`. Nút "+ Thêm sensor" trên panel.

**Tab Lịch sử**
- Nút chọn khoảng: `[24 giờ] [7 ngày] [30 ngày] [Tùy chọn…]`, chọn sensor `[Ping ▾]`.
- Biểu đồ đường Chart.js cao 240px: trục Y = ms, nền trắng, lưới xám nhạt, 1 đường màu `--nm-link`; các khoảng DOWN tô dải đỏ nhạt nền phía sau, PAUSED tô dải xanh nhạt.
- Dưới biểu đồ: 4 số `Uptime 99,82 % · Down 2 lần · Tổng thời gian down 14 phút · Trung bình 8 ms`.
- Bảng log check gần nhất (50 dòng): `Thời gian | Trạng thái | Giá trị | Thông điệp`.

**Tab Cấu hình**
```
┌─ Kết nối ─────────────────────────────────────────────────────────────┐
│ SSH · cổng 22 · user admin · driver VyOS   [Kiểm tra kết nối] ✓ OK 0,4s│
└───────────────────────────────────────────────────────────────────────┘
┌─ Thông tin ─────────────┐ ┌─ Thao tác nhanh ─────────────────────────┐
│ [Running-config][Interface][Routing] │ │ [Đổi hostname] [Đặt IP interface]     │
│ ┌─────────────────────┐ │ │ [Bật/Tắt interface]                     │
│ │ (hộp monospace,     │ │ └─────────────────────────────────────────┘
│ │  cuộn, chỉ đọc)     │ │ ┌─ Backup ───────────────────────────────┐
│ └─────────────────────┘ │ │ ☐ 22/11 14:00  4,2 KB  [Xem][Tải]        │
│ [Làm mới] [Sao chép]    │ │ ☐ 21/11 14:00  4,2 KB  [Xem][Tải]        │
└─────────────────────────┘ │ [Backup ngay] [So sánh 2 bản đã chọn]   │
                            └─────────────────────────────────────────┘
┌─ Lịch sử thay đổi ────────────────────────────────────────────────────┐
│ Thời gian │ Người dùng │ Thao tác              │ Lệnh   │ Trạng thái │      │
│ 14:03     │ admin      │ Tắt interface eth1    │ [Xem]  │ Đã chạy    │ [Hoàn tác] │
│ 13:50     │ admin      │ Đổi hostname R1→CORE1 │ [Xem]  │ Đã hoàn tác│            │
└───────────────────────────────────────────────────────────────────────┘
```
- Interface và Routing hiện dạng bảng (không phải text thô): `Interface | IP | Trạng thái (badge UP/DOWN) | Mô tả`.
- Mỗi thao tác nhanh mở modal: form nhỏ → nút "Xem trước lệnh" → hộp monospace liệt kê lệnh sẽ gửi → "Thực thi" (nút nguy hiểm với Tắt interface). Hệ thống backup tự động trước khi chạy; hiện dòng chú thích "Đã tự động backup lúc 14:03".
- Chỉ dòng mới nhất chưa hoàn tác mới có nút "Hoàn tác" sáng (FR-65); các dòng khác nút mờ + tooltip "Hoàn tác thao tác mới hơn trước".
- So sánh backup: trang/ modal diff 2 cột, dòng thêm nền xanh nhạt `#E6F4EA`, dòng bỏ nền đỏ nhạt `#FBE9E8`, monospace 12px.

**Tab Terminal**
- Khung xterm.js chiếm toàn chiều rộng, cao 480px, nền đen chữ xám nhạt (ngoại lệ duy nhất về nền tối).
- Thanh trên: `● Đã kết nối SSH 192.168.100.1 · 03:12` + nút [Ngắt kết nối] [Kết nối lại]. Cảnh báo vàng nhạt khi dùng Telnet: "Telnet gửi dữ liệu không mã hoá – chỉ dùng trong lab".
- Tự ngắt sau 10 phút không gõ, hiện thông báo trong terminal.

**Tab Nhật ký**: bảng audit log lọc theo thiết bị này.

### 5.5 Thêm / Sửa thiết bị — `/devices/new`, `/devices/<id>/edit` (F-02, F-16)
Form 2 cột (4.7), chia thành các panel xếp dọc:
1. **Thông tin cơ bản**: Loại thiết bị* (dropdown – đổi loại thì panel 2 đổi trường), Tên*, IP*, MAC, Hãng, Nhóm* (dropdown dạng cây), Vị trí, Ghi chú.
2. **Thuộc tính theo loại**: Router: Số interface · Switch: Số port, VLAN · Server: OS, Dịch vụ · Printer: Model.
3. **Quản trị từ xa** (thu gọn mặc định): Giao thức (SSH/Telnet), Cổng, Username, Password (ô password, khi sửa hiện "•••••• (để trống nếu không đổi)"), Driver. Nút [Kiểm tra kết nối].
4. **Sensor mặc định** (chỉ khi tạo mới): checkbox đã tick sẵn theo loại, VD Router: ☑ Ping ☑ Port 22 ☐ SNMP.

Kiểm tra lỗi ngay khi rời ô (IP sai định dạng, IP/tên trùng).

### 5.6 Thêm / Sửa sensor — modal (F-07, F-08, F-10)
Modal 520px: Loại sensor* (Ping, TCP Port, HTTP, DNS, SNMP — danh sách lấy từ SensorFactory) → các trường đổi theo loại:
- Chung: Tên, Chu kỳ (giây, 10–3600), Timeout, Số lần lỗi trước khi DOWN.
- Ping: Ngưỡng WARNING (ms), Ngưỡng mất gói (%).
- TCP Port: Cổng.
- HTTP: URL, Chuỗi cần có trong nội dung (tùy chọn), Ngưỡng thời gian phản hồi.
- DNS: Tên miền cần phân giải.
- SNMP: Community, OID (dropdown gợi ý: Uptime, CPU, Interface status), Ngưỡng.

### 5.7 Sensor — `/sensors` (F-07, F-09)
Bảng toàn bộ sensor kiểu trang "Sensors" PRTG: `☐ | Trạng thái | Sensor | Thiết bị | Nhóm | Loại | Giá trị cuối | Lần check cuối | Thông điệp | ⋯`. Bộ lọc nhanh dạng nút trạng thái có số: `[Tất cả 52] [■ Down 3] [■ Warning 5] [■ Up 42] [■ Paused 2]`. Thao tác hàng loạt: Tạm dừng, Tiếp tục, Check ngay, Xóa.

Trang chi tiết sensor `/sensors/<id>`: giống tab Lịch sử của thiết bị + panel cài đặt sensor.

### 5.8 Cảnh báo — `/alerts` (F-12, F-13)
- 2 tab: **Danh sách** | **Kênh thông báo** (Admin).
- Danh sách: bộ lọc `[Đang mở] [Đã xác nhận] [Đã giải quyết] [Tất cả]` + Mức + Khoảng thời gian. Bảng: `Mức | Thời gian | Thiết bị | Sensor | Trạng thái chuyển (UP → DOWN) | Thời lượng | Người xác nhận | Ghi chú | [Xác nhận]`.
- Nút Xác nhận mở modal nhỏ có ô ghi chú.
- Dòng OPEN in đậm; RESOLVED chữ muted.
- Tab Kênh thông báo: mỗi kênh 1 panel (Web, Log file, Email, Telegram) với công tắc Bật/Tắt, các trường cấu hình (SMTP, Bot token, Chat ID), nút [Gửi thử] và dòng kết quả gửi thử gần nhất.

### 5.9 Quét mạng — `/discovery` (F-06)
```
Dải IP (CIDR)* [192.168.100.0/24]   Cổng kiểm tra [22,23,80,443,161]   [Bắt đầu quét]
████████████░░░░░░░░  148 / 254 · tìm thấy 6 · còn ~12 giây                [Dừng]
┌──────────────────────────────────────────────────────────────────────────┐
│ ☐ │ IP              │ Hostname     │ Cổng mở    │ Đoán loại │ Trong kho │
│ ☐ │ 192.168.100.1   │ r1.lab       │ 22, 23, 161│ Router    │ ✓ Đã có   │
│ ☑ │ 192.168.100.10  │ srv-web.lab  │ 22, 80     │ Server    │           │
└──────────────────────────────────────────────────────────────────────────┘
Đã chọn 1   Thêm vào nhóm [Tầng 2 ▾]   [Thêm vào kho]
```
- CIDR lớn hơn /22 → lỗi ngay dưới ô.
- Dòng "Đã có" checkbox bị vô hiệu, chữ muted.
- Kết quả hiện dần theo tiến trình (poll `/api/discovery/<job_id>` mỗi 1 giây).

### 5.10 Báo cáo — `/reports` (F-14, F-15)
- Thanh lựa chọn: Khoảng thời gian `[7 ngày qua ▾]`, Nhóm `[Tất cả ▾]`, [Xem báo cáo], [Xuất CSV], [Xuất PDF].
- Hàng 4 số tổng: Số thiết bị · Uptime trung bình · Số lần DOWN · Tổng thời gian DOWN.
- Bảng: `Thiết bị | Nhóm | Uptime % | Số lần DOWN | Thời gian DOWN | Độ trễ TB | Độ trễ max`, mặc định sắp uptime tăng dần (tệ nhất lên đầu). Ô uptime < 99 % chữ đỏ.
- Bản PDF: cùng nội dung, khổ A4 dọc, tiêu đề + thời gian xuất + bảng, đen trắng trừ badge trạng thái.

### 5.11 Nhật ký — `/logs` (F-21)
Bảng audit log: `Thời gian | Người dùng | Hành động | Đối tượng | Chi tiết`, lọc theo người dùng, loại hành động, khoảng thời gian. Chỉ đọc.

### 5.12 Cài đặt — `/settings` (Admin)
Trang chia tab dọc bên trái (kiểu "Setup" của PRTG):
- **Tài khoản**: bảng người dùng `Tên | Vai trò | Trạng thái | Lần đăng nhập cuối | ⋯` + nút Thêm; modal tạo/sửa (Tên, Vai trò, Mật khẩu); hành động Khóa/Mở khóa, Đặt lại mật khẩu.
- **Nhóm**: cây nhóm có kéo thả, thêm/đổi tên/xóa (không xóa nhóm còn thiết bị).
- **Giám sát**: Chu kỳ mặc định, Số lần lỗi trước khi DOWN, Số ngày giữ lịch sử, Giờ backup cấu hình hằng ngày.
- **Hệ thống**: Phiên bản, Trạng thái scheduler (đang chạy, số sensor, số luồng), nút [Khởi động lại scheduler].

---

## 6. Hành vi realtime

| Sự kiện WebSocket (`/ws/status`) | Cập nhật trên giao diện |
|---|---|
| `sensor_status_changed` | Đổi màu ô sensor, chấm thiết bị, chấm nhóm cha, thanh tổng trên header, ô tổng dashboard; toast nếu chuyển DOWN hoặc khôi phục UP |
| `sensor_result` | Cập nhật giá trị cuối và "lần check cuối" nếu ô đó đang hiển thị |
| `alert_opened` / `alert_updated` | Số trong menu "Cảnh báo (n)", danh sách cảnh báo dashboard |
| Mất kết nối | Footer chuyển xám "Mất kết nối – đang thử lại…", tự kết nối lại mỗi 5 giây |

Không reload cả trang; chỉ thay phần tử theo `data-sensor-id`, `data-device-id`, `data-group-id`.

---

## 7. Phân quyền trên giao diện

| Thành phần | Admin | Operator | Viewer |
|---|---|---|---|
| Thêm/Sửa/Xóa thiết bị, nhóm, sensor | ✓ | – | – |
| Tạm dừng/Tiếp tục sensor | ✓ | – | – |
| Xác nhận cảnh báo | ✓ | ✓ | – |
| Tab Cấu hình | ✓ (đầy đủ) | ✓ (chỉ xem) | – |
| Tab Terminal | ✓ | – | – |
| Quét mạng, Cài đặt | ✓ | – | – |
| Dashboard, Thiết bị, Sensor, Báo cáo, Nhật ký | ✓ | ✓ | ✓ |

Phần tử không có quyền thì **ẩn**, không chỉ làm mờ. Backend vẫn kiểm tra quyền (FR-03).

---

## 8. Ghi chú triển khai

**Cấu trúc template**
```
templates/
├── base.html                 # header, menu, breadcrumb, footer, toast container
├── components/
│   ├── status.html           # status_badge, status_dot, sensor_tile
│   ├── table.html            # data_table, pagination
│   ├── panel.html
│   ├── form.html             # form_row, form_errors
│   └── modal.html            # confirm_modal
├── auth/login.html
├── dashboard.html
├── devices/{list.html, detail.html, form.html}
├── sensors/{list.html, detail.html, _form_modal.html}
├── alerts/index.html
├── discovery/index.html
├── reports/index.html
├── logs/index.html
└── settings/index.html
static/
├── css/netmon.css            # tokens mục 2 + ghi đè Bootstrap
└── js/{realtime.js, tree.js, table.js, charts.js, terminal.js}
```

**Quy tắc**
- Bootstrap 5 chỉ dùng grid, form, modal, dropdown; ghi đè màu, bo góc, đổ bóng theo mục 2 (`--bs-border-radius: 2px`, `box-shadow: none`).
- Không dùng thư viện UI khác (không Material, không Tailwind).
- JS thuần (vanilla) + Socket.IO client + Chart.js + xterm.js; không cần React/Vue.
- Màu trạng thái lấy từ một chỗ duy nhất: class `.st-up`, `.st-warning`, `.st-down`, `.st-down-ack`, `.st-paused`, `.st-unknown`; template chỉ gọi macro, không tự viết màu.
- Mọi chuỗi giao diện bằng tiếng Việt; tên trạng thái giữ tiếng Anh (UP, DOWN…) như PRTG để ngắn gọn.
- Độ rộng tối thiểu hỗ trợ: 1280px (NFR-08); không cần giao diện điện thoại.

**Tiêu chí nghiệm thu giao diện**
1. Tắt router trong lab → trong ≤ 2 giây ô sensor, chấm thiết bị, chấm nhóm và thanh tổng trên header cùng chuyển đỏ mà không reload trang.
2. Ngoài màu trạng thái, chụp màn hình bất kỳ trang nào chỉ thấy trắng, xám, xanh than và xanh dương link.
3. Mọi hành động xóa, tắt interface, thực thi lệnh đều có hộp xác nhận.
4. Đăng nhập bằng Viewer không thấy bất kỳ nút sửa/xóa/cấu hình nào.
