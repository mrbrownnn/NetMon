"""Scheduler integration and result/status observers."""
import logging
import math
from datetime import datetime, timedelta
from threading import Event, Thread

from sqlalchemy import delete, select
from netmon.domain.scheduler import MonitorScheduler
from netmon.domain.sensors import SensorFactory
from netmon.domain.status import Status
from netmon.infra import db as m
from netmon.infra.repositories import SqlSensorRepository
from .common import date, paginate, require, row_dict
from .errors import ValidationError


class ResultRecorder:
    def __init__(self, service):
        self.service = service

    def on_status_changed(self, sensor, old, result):
        with self.service.db.session() as s:
            row = s.get(m.Sensor, sensor.id)
            if row:
                row.status, row.paused = result.status.value, sensor.paused

    def on_result(self, sensor, result):
        self.service.record(sensor, result)


class WebSocketPublisher:
    def __init__(self, service):
        self.service = service

    def on_status_changed(self, sensor, old, result):
        service = self.service
        device = service.inventory.get_device(sensor.device_id)
        ids = service.inventory.ancestor_ids(device["group_id"])
        statuses = {}
        def walk(nodes):
            for n in nodes:
                if n["id"] in ids:
                    statuses[str(n["id"])] = n["status"]
                walk(n["children"])
        walk(service.inventory.groups_tree())
        service.publisher("sensor_status_changed", {"sensor_id": sensor.id,
            "device_id": sensor.device_id, "group_ids": ids, "old": old.value,
            "new": result.status.value, "value": result.value, "message": result.message,
            "counts": service.counts(), "device_status": device["status"], "group_statuses": statuses})

    def on_result(self, sensor, result):
        self.service.publisher("sensor_result", {"sensor_id": sensor.id, "device_id": sensor.device_id,
            "value": result.value, "unit": "" if sensor.type_name == "snmp" else "ms",
            "ts": result.ts.isoformat(), "message": result.message, "status": result.status.value})


class AlertObserver:
    """Record old status without changing public domain AlertManager signatures."""
    def __init__(self, service, manager):
        self.service, self.manager = service, manager

    def on_status_changed(self, sensor, old, result):
        self.manager.repository.context.old_status = old.value
        try:
            self.manager.on_status_changed(sensor, old, result)
        finally:
            del self.manager.repository.context.old_status

    def on_result(self, sensor, result):
        pass


class MonitorService:
    def __init__(self, db, audit, settings, inventory, publisher, alert_manager):
        self.db, self.audit, self.settings, self.inventory = db, audit, settings, inventory
        self.publisher = publisher
        self.repository = SqlSensorRepository(db)
        self.scheduler = MonitorScheduler.instance()
        self.sensors = {}
        self.recorder, self.websocket = ResultRecorder(self), WebSocketPublisher(self)
        self.alert_observer = AlertObserver(self, alert_manager)
        self.stop_event = Event()
        self.maintenance_thread = None
        self.config = None
        for sensor in self.repository.list():
            self.register(sensor)

    def register(self, sensor):
        sensor.attach(self.recorder)
        sensor.attach(self.websocket)
        sensor.attach(self.alert_observer)
        self.sensors[sensor.id] = sensor
        self.scheduler.add_sensor(sensor)

    def unregister(self, sensor_id):
        obj = self.sensors.pop(sensor_id, None)
        self.scheduler.remove_sensor(sensor_id)
        if obj:
            # Wait for any active run before deletion, then prevent future callbacks.
            with obj._lock:
                obj.detach(self.recorder)
                obj.detach(self.websocket)
                obj.detach(self.alert_observer)

    def build_sensor(self, data):
        kind = data.get("sensor_type", data.get("type", "ping"))
        params = data.get("params") or {}
        if kind not in SensorFactory.types() or not isinstance(params, dict):
            raise ValidationError({"sensor_type": "Loại hoặc tham số không hợp lệ"})
        params = dict(params)
        errors = {}
        for k, spec in SensorFactory.types()[kind].params_schema.items():
            value = params.get(k, spec.get("default"))
            try:
                value = int(value) if spec["type"] == "int" else str(value)
                if k == "port" and not 1 <= value <= 65535:
                    raise ValueError()
                if k == "count" and not 1 <= value <= 100:
                    raise ValueError()
                params[k] = value
            except (ValueError, TypeError):
                errors[f"params.{k}"] = "Giá trị không hợp lệ"
        values = {"interval": data.get("interval", self.settings.get("default_interval")),
            "timeout": data.get("timeout", 5), "warning_threshold": data.get("warning_threshold"),
            "down_after": data.get("down_after", self.settings.get("down_after"))}
        for key, value in values.items():
            if value is not None:
                try:
                    if not math.isfinite(float(value)):
                        raise ValueError()
                except (ValueError, TypeError):
                    errors[key] = "Giá trị không hợp lệ"
        if errors:
            raise ValidationError(errors)
        try:
            return SensorFactory.create(kind, id=data.get("id"), device_id=data["device_id"],
                name=data.get("name", kind.upper()), target=data.get("target", ""),
                params=params, paused=bool(data.get("paused", False)), **values)
        except (ValueError, TypeError) as e:
            field = next((k for k in values if k in str(e)), "sensor")
            raise ValidationError({field: str(e)}) from None

    def add_sensor(self, device_id, data, actor=None):
        device = self.inventory.get_device(device_id)
        obj = self.build_sensor({"target": device["ip"], **data, "device_id": device_id})
        self.repository.add(obj)
        self.register(obj)
        self.audit.log(actor, "sensor_create", obj.id)
        return self.get_sensor(obj.id)

    def get_sensor(self, sensor_id):
        with self.db.session() as s:
            result = row_dict(require(s, m.Sensor, sensor_id))
            last = s.scalar(select(m.CheckResult).where(m.CheckResult.sensor_id == sensor_id).order_by(m.CheckResult.ts.desc(), m.CheckResult.id.desc()).limit(1))
            result["last_result"] = row_dict(last) if last else None
        return result

    def update_sensor(self, sensor_id, data, actor=None):
        current = self.get_sensor(sensor_id)
        merged = {**current, **data}
        if "type" in data and "sensor_type" not in data:
            merged["sensor_type"] = data["type"]
        obj = self.build_sensor(merged)
        old = self.sensors[sensor_id]
        obj._status = old.status
        obj._last_result = old.last_result
        obj._failures = old.consecutive_failures
        obj._paused = old.paused
        self.unregister(sensor_id)
        self.repository.update(obj)
        self.register(obj)
        if "paused" in data:
            self.pause_sensor(sensor_id, bool(data["paused"]), actor)
        self.audit.log(actor, "sensor_update", sensor_id)
        return self.get_sensor(sensor_id)

    def delete_sensor(self, sensor_id, actor=None):
        self.get_sensor(sensor_id)
        self.unregister(sensor_id)
        self.repository.delete(sensor_id)
        self.audit.log(actor, "sensor_delete", sensor_id)
        return {"ok": True}

    def record(self, sensor, result):
        with self.db.session() as s:
            row = s.get(m.Sensor, sensor.id)
            if row is None:
                return
            row.status, row.paused = result.status.value, sensor.paused
            s.add(m.CheckResult(sensor_id=sensor.id, ts=date(result.ts), status=result.status.value,
                value=result.value, message=result.message))

    def pause_sensor(self, sensor_id, paused=True, actor=None):
        sensor = self.sensors.get(sensor_id)
        if sensor is None:
            raise KeyError(sensor_id)
        sensor.pause() if paused else sensor.resume()
        from netmon.domain.status import CheckResult
        self.record(sensor, CheckResult(sensor.status, None, "Paused" if paused else "Resumed"))
        self.audit.log(actor, "sensor_pause" if paused else "sensor_resume", sensor_id)
        return self.get_sensor(sensor_id)

    def resume_sensor(self, sensor_id, actor=None):
        return self.pause_sensor(sensor_id, False, actor)

    def pause_device(self, device_id, paused=True, actor=None):
        device = self.inventory.get_device(device_id)
        for row in device["sensors"]:
            self.pause_sensor(row["id"], paused, actor)
        return self.inventory.get_device(device_id)

    def resume_device(self, device_id, actor=None):
        return self.pause_device(device_id, False, actor)

    def pause_group(self, group_id, paused=True, actor=None):
        for d in self.inventory.list_devices(group=group_id, paginated=False):
            self.pause_device(d["id"], paused, actor)
        self.audit.log(actor, "group_pause" if paused else "group_resume", group_id)
        return self.inventory.groups_tree()

    def resume_group(self, group_id, actor=None):
        return self.pause_group(group_id, False, actor)

    def run_now(self, sensor_id, actor=None):
        if sensor_id not in self.sensors:
            raise KeyError(sensor_id)
        result = self.scheduler.run_now(sensor_id)
        self.audit.log(actor, "sensor_run_now", sensor_id)
        return {"status": result.status.value, "value": result.value, "message": result.message, "ts": result.ts.isoformat()}

    def counts(self):
        with self.db.session() as s:
            statuses = list(s.scalars(select(m.Sensor.status)))
        counts = {v.value: statuses.count(v.value) for v in Status}
        return {**counts, "total": len(statuses)}

    def list_sensors(self, q=None, type=None, group=None, status=None, device_id=None, page=1):
        devices = self.inventory.list_devices(q=q, group=group, paginated=False)
        ids = {d["id"] for d in devices}
        with self.db.session() as s:
            rows = [row_dict(r) for r in s.scalars(select(m.Sensor).order_by(m.Sensor.id))]
        rows = [r for r in rows if r["device_id"] in ids and (not type or r["sensor_type"] == type)
            and (not status or r["status"] == status) and (device_id is None or r["device_id"] == int(device_id))]
        counts = {st.value: sum(r["status"] == st.value for r in rows) for st in Status}
        return {**paginate(rows, page), "counts": {**counts, "total": len(rows)}}

    def sensor_results(self, sensor_id, from_=None, to=None):
        with self.db.session() as s:
            require(s, m.Sensor, sensor_id)
            q = select(m.CheckResult).where(m.CheckResult.sensor_id == sensor_id).order_by(m.CheckResult.ts, m.CheckResult.id)
            if from_:
                q = q.where(m.CheckResult.ts >= date(from_))
            if to:
                q = q.where(m.CheckResult.ts <= date(to))
            return [row_dict(r) for r in s.scalars(q)]

    def sensor_types(self):
        return [{"type": k, "name": cls.__name__, "params_schema": cls.params_schema} for k, cls in SensorFactory.types().items()]

    def purge_results(self, actor=None):
        before = datetime.now() - timedelta(days=self.settings.get("retention_days"))
        with self.db.session() as s:
            count = s.execute(delete(m.CheckResult).where(m.CheckResult.ts < before)).rowcount
        self.audit.log(actor, "results_purge", "check_results", {"deleted": count})
        return {"deleted": count}

    def stats(self):
        return self.scheduler.stats()

    def restart(self, actor=None):
        self.scheduler.stop()
        self.scheduler.start()
        self.audit.log(actor, "scheduler_restart", "scheduler")
        return self.stats()

    def start(self):
        self.scheduler.start()
        self.maintenance_thread = Thread(target=self._maintenance, daemon=True, name="netmon-maintenance")
        self.maintenance_thread.start()

    def _maintenance(self):
        last_purge = None
        last_backup = None
        while not self.stop_event.is_set():
            now = datetime.now()
            try:
                if last_purge != now.date():
                    self.purge_results()
                    last_purge = now.date()
                if self.config and now.hour == self.settings.get("backup_hour") and last_backup != now.date():
                    self.config.daily_backups()
                    last_backup = now.date()
            except Exception:
                logging.getLogger(__name__).exception("Scheduled maintenance failed")
            self.stop_event.wait(30)

    def close(self):
        self.stop_event.set()
        if self.maintenance_thread:
            self.maintenance_thread.join(timeout=5)
        self.scheduler.stop()
        for id in list(self.sensors):
            self.unregister(id)
