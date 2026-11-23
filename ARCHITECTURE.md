# Kiến trúc NetMon

```mermaid
flowchart TB
    user["Người dùng<br/>Admin · Operator · Viewer"]

    subgraph browser["Trình duyệt"]
        spa["React 19 + TypeScript SPA<br/>Vite · Bootstrap 5 · Chart.js · socket.io-client"]
    end

    subgraph railway["Railway project (Docker)"]
        subgraph app["Service NetMon · Gunicorn 1 worker"]
            web["<b>netmon/web</b><br/>Flask REST API (85 route) · session + CSRF<br/>phân quyền theo vai trò · phục vụ SPA đã build<br/>Socket.IO /ws/status"]

            subgraph services["netmon/services"]
                facade["Facade NetMonService"]
                svcs["auth · inventory · monitor · alerts · reports<br/>config · discovery · audit · settings · gns3"]
            end

            subgraph domain["netmon/domain (thuần Python)"]
                nodes["Group / Device<br/><i>Composite · Factory</i>"]
                sensors["Sensor: Ping · Port · HTTP · DNS · SNMP<br/><i>Template Method · Observer · Factory</i>"]
                scheduler["MonitorScheduler<br/><i>Singleton · ThreadPoolExecutor</i>"]
                alertmgr["AlertManager → Notifier<br/>log · email · Telegram · web"]
                remote["Connection SSH / Telnet / Fake <i>Strategy</i><br/>DeviceDriver VyOS / MikroTik / Cisco <i>Adapter</i><br/>ConfigCommand + CommandHistory <i>Command</i>"]
                gns3c["Gns3Client: HttpGns3 / DemoGns3<br/><i>Strategy</i>"]
            end

            infra["<b>netmon/infra</b><br/>SQLAlchemy models · Repository · Fernet · cấu hình env"]
        end

        db[("PostgreSQL<br/>(local: SQLite)")]
    end

    subgraph external["Bên ngoài"]
        devices["Thiết bị mạng / lab"]
        gns3s["GNS3 server 2.2<br/>REST /v2"]
        smtp["SMTP"]
        tg["Telegram Bot API"]
    end

    user --> spa
    spa -- "HTTPS JSON" --> web
    web -. "WebSocket: trạng thái, cảnh báo" .-> spa
    web --> facade --> svcs
    svcs --> nodes & scheduler & alertmgr & remote & gns3c
    svcs --> infra --> db
    scheduler -- "chạy theo chu kỳ" --> sensors
    sensors -- "on_status_changed" --> alertmgr
    sensors -- "ping · TCP · HTTP · DNS · SNMP" --> devices
    remote -- "SSH / Telnet" --> devices
    alertmgr --> smtp & tg
    gns3c -- "project · node · link" --> gns3s
```

- Phụ thuộc chỉ đi từ ngoài vào trong: `web` → `services` → `domain`; `domain` không import Flask hay SQLAlchemy.
- Kết quả mỗi lần check được ghi vào CSDL và đẩy realtime tới trình duyệt; đổi trạng thái thì `AlertManager` tạo cảnh báo và gửi thông báo.
- Chạy 1 worker vì scheduler là singleton trong tiến trình. Railway không vào được lab/GNS3 trên laptop: giám sát lab thật thì chạy local (`docker compose up` hoặc `python run.py`).
