"""Explicit service adapters; permissions never delegated to UI."""
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, Response, abort, current_app, g, jsonify, request, session
from flask_wtf.csrf import generate_csrf

from netmon.domain.nodes import DeviceFactory
from netmon.domain.remote import DriverFactory

api = Blueprint("api", __name__, url_prefix="/api")
VERSION = "1.0.0"  # ponytail: hardcoded; read package metadata when NetMon gets a pyproject


def service():
    return current_app.extensions["netmon"]


def roles(*allowed):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                abort(401)
            if g.user["role"] not in allowed:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorate


admin = roles("admin")
operator = roles("admin", "operator")
reader = roles("admin", "operator", "viewer")


def body():
    data = request.get_json()
    if not isinstance(data, dict):
        abort(400, "JSON object required")
    return data


def groups():
    result = []
    def walk(nodes):
        for node in nodes:
            result.append({k: node[k] for k in ("id", "name", "parent_id")})
            walk(node["children"])
    walk(service().inventory.groups_tree())
    return result


def envelope(result, name):
    return {**result, name: result["items"], "pagination": {"page": result["page"],
        "pages": result["pages"], "total": result["total"], "per_page": 20}, "filters": request.args.to_dict()}


def filters():
    return {k: request.args[k] for k in ("q", "type", "status", "page") if request.args.get(k)} | ({"group": request.args["group_id"]} if request.args.get("group_id") else {})


def dates():
    end = request.args.get("end") or request.args.get("to")
    start = request.args.get("start") or request.args.get("from")
    if not start:
        hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720}.get(request.args.get("range", "24h"), 24)
        start = (datetime.now() - timedelta(hours=hours)).isoformat()
    return {"from_": start, "to": end}


def sensor(row):
    last = row.get("last_result") or {}
    return {**row, "type": row["sensor_type"], "last_value": last.get("value"),
        "last_check": last.get("ts"), "message": last.get("message", ""),
        "unit": "" if row["sensor_type"] == "snmp" else "ms"}


def tree():
    """Group tree with each device's sensors (dashboard tiles need them)."""
    sensors = {}
    for d in service().inventory.list_devices(paginated=False):
        sensors[d["id"]] = [sensor(service().monitor.get_sensor(r["id"])) for r in service().inventory.get_device(d["id"])["sensors"]]
    def walk(nodes):
        for node in nodes:
            for d in node["devices"]:
                d["sensors"] = sensors.get(d["id"], [])
            walk(node["children"])
        return nodes
    return walk(service().inventory.groups_tree())


def schemas(items, field):
    return {v["type"]: {"label": v["name"].removesuffix("Sensor"), field: {k: {**spec, "label": spec.get("label", k),
        "type": "number" if spec["type"] == "int" else "text"} for k, spec in v[field].items()}} for v in items}


def device_type_schemas():
    # FR-12: default sensor types per device type, so the form pre-ticks them. Placeholder IP only builds the list.
    result = schemas(service().inventory.device_types(), "extra_fields")
    for key, spec in result.items():
        spec["default_sensors"] = [s["type"] for s in DeviceFactory.create(key, id=None, name="_", ip="0.0.0.0").default_sensors()]
    return result


@api.get("/auth/session")
def auth_session():
    return jsonify(user=g.user, csrf_token=generate_csrf())


@api.post("/auth/login")
def login():
    data = body()
    user = service().auth.login(str(data.get("username", "")), str(data.get("password", "")))
    session.clear()
    session.update(user_id=user["id"], pw=current_app.fingerprint(user["id"]), sid=secrets.token_hex(16))
    return jsonify(user=user, csrf_token=generate_csrf())


@api.post("/auth/logout")
@reader
def logout():
    from netmon.web import socketio
    room = f"session:{session.get('sid')}"
    for sid, _ in list(socketio.server.manager.get_participants("/ws/status", room)):
        socketio.server.disconnect(sid, namespace="/ws/status")
    service().audit.log(g.user, "logout", "auth")
    session.clear()
    return jsonify(user=None, csrf_token=generate_csrf())


@api.post("/account/password")
@api.post("/auth/password")
@reader
def own_password():
    data = body()
    new = data.get("new_password", "")
    if "confirm_password" in data and new != data["confirm_password"]:
        abort(400, "Password confirmation does not match")
    service().auth.change_password(g.user["id"], data.get("current_password", data.get("old_password", "")), new, g.user)
    session["pw"] = current_app.fingerprint(g.user["id"])  # keep this session; others now mismatch
    return jsonify(ok=True)


@api.get("/dashboard")
@reader
def dashboard():
    sensors = [{**sensor(service().monitor.get_sensor(r["id"])), "device_name": d["name"]} for d in service().inventory.list_devices(paginated=False) for r in service().inventory.get_device(d["id"])["sensors"]]
    top = sorted((s for s in sensors if s["last_value"] is not None and s["type"] != "snmp"), key=lambda s: s["last_value"], reverse=True)[:10]
    return jsonify(status_counts=service().monitor.counts(), open_alert_count=service().alerts.open_count(), open_alerts=service().alerts.list(state="OPEN")["items"], top_latency=top, tree=tree())


@api.get("/devices")
@reader
def devices():
    all_groups = groups()
    names = {x["id"]: x["name"] for x in all_groups}
    result = service().inventory.list_devices(**filters())
    result["items"] = [{**d, "group_name": names.get(d["group_id"])} for d in result["items"]]
    return jsonify(**envelope(result, "devices"), groups=all_groups, tree=tree())


@api.get("/devices/form")
@admin
def device_form():
    values = service().inventory.get_device(int(request.args["id"])) if request.args.get("id") else {}
    if values.get("credential"):
        values.update(values["credential"])
        values["id"] = int(request.args["id"])
    return jsonify(values=values, errors={}, device_types=device_type_schemas(),
        sensor_types=schemas(service().monitor.sensor_types(), "params_schema"), groups=groups(), drivers=sorted(DriverFactory.types()))


def save_credentials(device_id, data):
    if any(k in data for k in ("protocol", "driver", "username", "password")):
        values = dict(data)
        if not values.get("password"):
            values.pop("password", None)
        service().config.save_credentials(device_id, values, g.user)


@api.post("/devices")
@admin
def create_device():
    data = body()
    result = service().inventory.create_device(data, g.user)
    save_credentials(result["id"], data)
    return jsonify(result), 201


@api.get("/devices/<int:id>")
@reader
def device_detail(id):
    device = service().inventory.get_device(id)
    sensors = [sensor(service().monitor.get_sensor(r["id"])) for r in device["sensors"]]
    selected = int(request.args["sensor_id"]) if request.args.get("sensor_id") else (sensors[0]["id"] if sensors else None)
    if selected is not None and selected not in {s["id"] for s in sensors}:
        abort(404)
    history = service().monitor.sensor_results(selected, **dates()) if selected else []
    config_allowed = g.user["role"] in ("admin", "operator") and bool(device.get("credential"))
    backups, changes = [], []
    if config_allowed:
        backups = [backup_shape(service().config.get_backup(b["id"])) for b in service().config.list_backups(id)]
        changes = [change_shape(c) for c in service().config.history(id)]
    cred = device.pop("credential", None) or {}
    if g.user["role"] != "viewer":
        device["credential"] = cred
        device.update({k: cred.get(k) for k in ("protocol", "driver", "port", "username")})
    checks = [s["last_check"] for s in sensors if s["last_check"]]
    device.update(paused=bool(sensors) and all(s["paused"] for s in sensors), last_check=max(checks, default=None),
        group_name=next((x["name"] for x in groups() if x["id"] == device["group_id"]), None))
    return jsonify(device=device, sensors=sensors, history=history, history_summary=service().reports.device_summary(id, **dates()), backups=backups,
        config_history=changes, logs=[], capabilities={"config": config_allowed, "terminal": False})


@api.put("/devices/<int:id>")
@admin
def update_device(id):
    data = body()
    result = service().inventory.update_device(id, data, g.user)
    save_credentials(id, data)
    return jsonify(result)


@api.delete("/devices/<int:id>")
@admin
def delete_device(id):
    return jsonify(service().inventory.delete_device(id, g.user))


@api.post("/devices/<int:id>/pause")
@admin
def pause_device(id):
    return jsonify(service().monitor.pause_device(id, actor=g.user))


@api.post("/devices/<int:id>/resume")
@admin
def resume_device(id):
    return jsonify(service().monitor.resume_device(id, actor=g.user))


@api.post("/devices/<int:id>/move")
@admin
def move_device(id):
    return jsonify(service().inventory.move_device(id, body().get("group_id"), g.user))


@api.post("/devices/bulk")
@admin
def bulk_devices():
    data = body()
    ids, action = data.get("ids"), data.get("action")
    if not isinstance(ids, list) or len(ids) > 500 or not all(type(i) is int for i in ids) or action not in ("pause", "resume", "delete", "move"):
        abort(400, "Invalid bulk action or ids")
    for id in ids:
        service().inventory.get_device(id)
    for id in ids:
        if action == "pause":
            service().monitor.pause_device(id, actor=g.user)
        elif action == "resume":
            service().monitor.resume_device(id, actor=g.user)
        elif action == "delete":
            service().inventory.delete_device(id, g.user)
        else:
            service().inventory.move_device(id, data.get("group_id"), g.user)
    return jsonify(ok=True, count=len(ids))


@api.get("/groups")
@reader
def list_groups():
    return jsonify(groups=groups(), tree=tree())


@api.post("/groups")
@api.post("/settings/groups")
@admin
def create_group():
    data = body()
    return jsonify(service().inventory.create_group(data.get("name"), data.get("parent_id"), g.user)), 201


@api.put("/groups/<int:id>")
@api.put("/settings/groups/<int:id>")
@admin
def update_group(id):
    data = body()
    if "parent_id" in data:
        service().inventory.move_group(id, data["parent_id"], g.user)
    return jsonify(service().inventory.rename_group(id, data["name"], g.user))


@api.delete("/groups/<int:id>")
@api.delete("/settings/groups/<int:id>")
@admin
def delete_group(id):
    return jsonify(service().inventory.delete_group(id, g.user))


@api.post("/groups/<int:id>/pause")
@admin
def pause_group(id):
    return jsonify(tree=service().monitor.pause_group(id, actor=g.user))


@api.post("/groups/<int:id>/resume")
@admin
def resume_group(id):
    return jsonify(tree=service().monitor.resume_group(id, actor=g.user))


@api.get("/sensors")
@reader
def sensors():
    result = service().monitor.list_sensors(**filters(), device_id=request.args.get("device_id"))
    names = {d["id"]: d["name"] for d in service().inventory.list_devices(paginated=False)}
    result["items"] = [{**sensor(service().monitor.get_sensor(s["id"])), "device_name": names.get(s["device_id"])} for s in result["items"]]
    return jsonify(**envelope(result, "sensors"), groups=groups(), status_counts=result["counts"])


@api.get("/sensors/types")
@reader
def sensor_types():
    return jsonify(items=service().monitor.sensor_types(), sensor_types=schemas(service().monitor.sensor_types(), "params_schema"))


@api.get("/sensors/form")
@admin
def sensor_form():
    values = sensor(service().monitor.get_sensor(int(request.args["id"]))) if request.args.get("id") else {"device_id": request.args.get("device_id", type=int)}
    return jsonify(values=values, errors={}, sensor_types=schemas(service().monitor.sensor_types(), "params_schema"), devices=service().inventory.list_devices(paginated=False))


@api.get("/sensors/<int:id>")
@reader
def sensor_detail(id):
    value = sensor(service().monitor.get_sensor(id))
    device = service().inventory.get_device(value["device_id"])
    device.pop("credential", None)
    summary = service().reports.uptime(id, **dates())
    return jsonify(sensor=value, device=device, history=service().monitor.sensor_results(id, **dates()), history_summary={**summary, "down_seconds": summary["total_down_seconds"]})


@api.get("/sensors/<int:id>/results")
@reader
def results(id):
    return jsonify(items=service().monitor.sensor_results(id, **dates()))


@api.post("/sensors")
@admin
def create_sensor():
    data = body()
    if type(data.get("device_id")) is not int:
        abort(400, "device_id required")
    return jsonify(service().monitor.add_sensor(data["device_id"], data, g.user)), 201


@api.put("/sensors/<int:id>")
@admin
def update_sensor(id):
    return jsonify(service().monitor.update_sensor(id, body(), g.user))


@api.delete("/sensors/<int:id>")
@admin
def delete_sensor(id):
    return jsonify(service().monitor.delete_sensor(id, g.user))


@api.post("/sensors/<int:id>/pause")
@admin
def pause_sensor(id):
    return jsonify(service().monitor.pause_sensor(id, actor=g.user))


@api.post("/sensors/<int:id>/resume")
@admin
def resume_sensor(id):
    return jsonify(service().monitor.resume_sensor(id, actor=g.user))


@api.post("/sensors/<int:id>/check")
@admin
def check_sensor(id):
    return jsonify(service().monitor.run_now(id, g.user))


@api.get("/alerts")
@reader
def alerts():
    state = request.args.get("state", "OPEN")
    result = service().alerts.list(state=None if state == "ALL" else state, level=request.args.get("level"), page=request.args.get("page", 1), **dates())
    now = datetime.now()
    for a in result["items"]:
        end = datetime.fromisoformat(a["resolved_at"]) if a.get("resolved_at") else now
        a.update(note=a.get("ack_note", ""), duration_seconds=max(0, int((end - datetime.fromisoformat(a["opened_at"])).total_seconds())))
    return jsonify(envelope(result, "alerts"))


@api.post("/alerts/<int:id>/ack")
@operator
def ack(id):
    return jsonify(service().alerts.ack(id, body().get("note", ""), g.user))


@api.get("/alerts/channels")
@admin
def channels():
    items = []
    defaults = {"email": {"host": "", "port": 587, "sender": "", "recipients": [], "username": "", "password": "", "use_tls": True},
        "telegram": {"token": "", "chat_id": ""}}
    for row in service().alerts.channels():
        config = {**defaults.get(row["name"], {}), **row["config"]}
        fields = [{"name": k, "label": k, "type": "password" if k in ("password", "token") else "checkbox" if isinstance(v, bool) else "number" if isinstance(v, int) else "text", **({"value": ",".join(v) if isinstance(v, list) else v} if k not in ("password", "token") else {})} for k, v in config.items()]
        items.append({**row, "id": row["name"], "fields": fields, "last_test": row.get("last_test_result")})
    return jsonify(channels=items, items=items)


@api.put("/alerts/channels/<name>")
@admin
def update_channel(name):
    data = body()
    config = data.get("config", {k: v for k, v in data.items() if k != "enabled"})
    if not isinstance(config, dict) or type(data.get("enabled", False)) is not bool:
        abort(400, "Invalid channel configuration")
    if isinstance(config.get("recipients"), str):
        config["recipients"] = [v.strip() for v in config["recipients"].split(",") if v.strip()]
    if "port" in config:
        config["port"] = int(config["port"])
    for key in ("password", "token"):
        if not config.get(key):
            config.pop(key, None)
    return jsonify(service().alerts.update_channel(name, data.get("enabled", False), config, g.user))


@api.post("/alerts/channels/<name>/test")
@admin
def test_channel(name):
    return jsonify(service().alerts.send_test(name, g.user))


def backup_shape(row):
    return {**row, "created_at": row["ts"], "config": row.get("content"), "size": len(row.get("content", "").encode())}


def change_shape(row):
    return {**row, "executed_at": row["ts"], "commands": row["forward_cmds"], "description": row["command_type"]}


@api.get("/devices/<int:id>/config/credentials")
@operator
def credentials(id):
    return jsonify(credential=service().config.credentials(id))


@api.put("/devices/<int:id>/config/credentials")
@admin
def credentials_save(id):
    data = body()
    if not data.get("password"):
        data.pop("password", None)
    return jsonify(service().config.save_credentials(id, data, g.user))


@api.post("/devices/<int:id>/config/connection")
@operator
def connection(id):
    result = service().config.connection_test(id, g.user)
    return jsonify(**result, elapsed_ms=round(result["elapsed"] * 1000))


@api.get("/devices/<int:id>/config/running")
@operator
def running(id):
    result = service().config.running_config(id)
    return jsonify(**result, config=result["content"])


@api.get("/devices/<int:id>/config/interfaces")
@operator
def interfaces(id):
    return jsonify(interfaces=service().config.interfaces(id))


@api.get("/devices/<int:id>/config/routes")
@operator
def routes(id):
    return jsonify(routes=service().config.routes(id))


@api.get("/devices/<int:id>/config/backups")
@operator
def backups(id):
    return jsonify(backups=[backup_shape(service().config.get_backup(b["id"])) for b in service().config.list_backups(id)])


@api.post("/devices/<int:id>/config/backup")
@admin
def backup(id):
    result = service().config.create_backup(id, g.user)
    return jsonify(backup=backup_shape(result)) if result["ok"] else (jsonify(result), 502)


@api.get("/devices/<int:id>/config/diff")
@operator
def diff(id):
    a, b = request.args.get("a", type=int), request.args.get("b", type=int)
    for backup_id in (a, b):
        if service().config.get_backup(backup_id)["device_id"] != id:
            abort(404)
    return jsonify(diff=service().config.diff(a, b))


@api.post("/devices/<int:id>/config/preview")
@admin
def preview(id):
    data = body()
    return jsonify(service().config.preview(id, data.get("command_type"), data.get("params", {})))


@api.post("/devices/<int:id>/config/execute")
@admin
def execute(id):
    data = body()
    return device_result(service().config.execute(id, data.get("command_type"), data.get("params", {}), g.user))


def device_result(result):
    # Device rejected command: 400; could not connect/back up: 502. Never 200 for ok:false.
    if result.get("ok"):
        return jsonify(result)
    message = result.get("message") or "Thiết bị từ chối lệnh"
    return jsonify({**result, "error": message, "message": message}), 400 if result.get("kind") == "command" else 502


@api.post("/devices/<int:id>/config/undo")
@admin
def undo(id):
    change_id = body().get("command_id")
    if change_id not in {r["id"] for r in service().config.history(id)}:
        abort(404)
    return device_result(service().config.undo(change_id, g.user))


@api.post("/devices/<int:id>/config/terminal")
@admin
def terminal(id):
    service().inventory.get_device(id)
    abort(501, "Interactive terminal is not supported")


@api.get("/settings")
@admin
def settings():
    values = service().settings.get()
    return jsonify(users=[{**u, "locked": u["is_locked"]} for u in service().auth.users()], groups=groups(),
        values={**values, "history_days": values["retention_days"], "backup_time": f"{values['backup_hour']:02d}:00"}, errors={}, system=system())


def system():
    stats = service().monitor.stats()
    return {**stats, "scheduler_running": stats["running"], "worker_count": stats["threads"], "version": VERSION}


@api.put("/settings")
@api.put("/settings/monitoring")
@admin
def settings_update():
    data = body()
    if "history_days" in data:
        data["retention_days"] = data.pop("history_days")
    if "backup_time" in data:
        data["backup_hour"] = int(str(data.pop("backup_time")).split(":")[0])
    return jsonify(service().settings.set(data, g.user))


@api.post("/settings/scheduler/restart")
@admin
def restart():
    return jsonify(service().monitor.restart(g.user))


@api.get("/users")
@admin
def users():
    return jsonify(items=service().auth.users())


@api.post("/users")
@api.post("/settings/users")
@admin
def user_create():
    data = body()
    return jsonify(service().auth.create(data.get("username", ""), data.get("password", ""), data.get("role", "viewer"), g.user)), 201


@api.put("/users/<int:id>")
@api.put("/settings/users/<int:id>")
@admin
def user_update(id):
    data = body()
    if id == g.user["id"] and data.get("role") != "admin":
        abort(400, "Cannot demote current administrator")
    if "username" in data and data["username"] != service().auth.get(id)["username"]:
        abort(400, "Renaming users is not supported")
    return jsonify(service().auth.set_role(id, data.get("role"), g.user))


@api.delete("/users/<int:id>")
@admin
def user_delete(id):
    if id == g.user["id"]:
        abort(400, "Cannot delete current administrator")
    return jsonify(service().auth.delete(id, g.user))


@api.post("/users/<int:id>/lock")
@api.post("/settings/users/<int:id>/lock")
@admin
def user_lock(id):
    if id == g.user["id"]:
        abort(400, "Cannot lock current administrator")
    return jsonify(service().auth.lock(id, g.user))


@api.post("/users/<int:id>/unlock")
@api.post("/settings/users/<int:id>/unlock")
@admin
def user_unlock(id):
    return jsonify(service().auth.unlock(id, g.user))


@api.post("/users/<int:id>/password")
@api.post("/settings/users/<int:id>/password")
@admin
def user_password(id):
    return jsonify(service().auth.reset_password(id, body().get("password", ""), g.user))


@api.get("/reports")
@reader
def reports():
    report = service().reports.group_report(group=request.args.get("group_id"), **dates())
    names = {g["id"]: g["name"] for g in groups()}
    devices = {d["id"]: d for d in service().inventory.list_devices(paginated=False)}
    rows = [{**r, "device_name": r["name"], "group_name": names.get(devices[r["device_id"]]["group_id"], ""),
        "down_seconds": r["total_down_seconds"], "average_ms": r["avg_latency"], "max_ms": r["max_latency"]} for r in report["items"]]
    return jsonify(rows=rows, summary={**report, "down_seconds": report["total_down_seconds"]},
        filters=request.args.to_dict(), groups=groups(), pdf_supported=True)


@api.get("/reports/export.csv")
@reader
def report_csv():
    return Response(service().reports.export_csv(group=request.args.get("group_id"), **dates()),
        mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="netmon-report.csv"'})


@api.get("/reports/export.pdf")
@reader
def report_pdf():
    return Response(service().reports.export_pdf(group=request.args.get("group_id"), **dates()),
        mimetype="application/pdf", headers={"Content-Disposition": 'attachment; filename="netmon-report.pdf"'})


@api.get("/logs")
@api.get("/audit")
@reader  # UI-DESIGN §7: Nhật ký is visible to every role
def logs():
    result = service().audit.query(user_id=request.args.get("user_id") or None,
        action=request.args.get("action") or None, page=request.args.get("page", 1), **dates())
    result["items"] = [{**r, "created_at": r["ts"], "object": r["target"], "details": r["detail"]} for r in result["items"]]
    users = [{"id": u["id"], "username": u["username"]} for u in service().auth.users()]
    return jsonify(**envelope(result, "logs"), users=users, actions=service().audit.actions())


def job_shape(id, job):
    return {**job, "id": id, "completed": job["done"],
        "status": "stopped" if job["cancelled"] else "completed" if job["finished"] else "running",
        "results": [{**r, "ports": r["open_ports"], "type": r["guess"], "exists": r["in_inventory"]} for r in job["results"]]}


@api.post("/discovery")
@admin
def discovery_start():
    data = body()
    ports = data.get("ports")
    if isinstance(ports, str):
        ports = [int(p.strip()) for p in ports.split(",") if p.strip()]
    if ports is not None and not isinstance(ports, list):
        abort(400, "ports must be a list or comma-separated numbers")
    id = service().discovery.start(data.get("cidr"), ports, g.user)
    return jsonify(id=id), 202


@api.get("/discovery/<id>")
@admin
def discovery_status(id):
    return jsonify(job_shape(id, service().discovery.status(id)))


@api.post("/discovery/<id>/stop")
@api.post("/discovery/<id>/cancel")
@admin
def discovery_stop(id):
    return jsonify(job_shape(id, service().discovery.cancel(id, g.user)))


@api.post("/discovery/<id>/import")
@admin
def discovery_import(id):
    data = body()
    ips = data.get("ips")
    if not isinstance(ips, list) or not all(isinstance(ip, str) for ip in ips):
        abort(400, "ips must be an array of IPv4 addresses")
    allowed = {r["ip"] for r in service().discovery.status(id)["results"] if not r["in_inventory"]}
    if not set(ips) <= allowed:
        abort(400, "Selected IP is missing from this job or already exists")
    return jsonify(service().discovery.add_selected(ips, data.get("group_id"), g.user))


@api.get("/devices/export.csv")
@admin
def devices_export():
    return Response(service().inventory.export_csv(g.user, **filters()), mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="devices.csv"'})


@api.post("/devices/import")
@admin
def devices_import():
    upload = request.files.get("file")
    if upload is None:
        abort(400, "CSV file required")
    return jsonify(service().inventory.import_csv(upload.read(), g.user))

