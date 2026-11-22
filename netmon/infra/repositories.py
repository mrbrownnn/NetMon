"""Domain repository implementations. No live ORM objects escape sessions."""
from threading import local
from sqlalchemy import select

from netmon.domain.alerts import Alert, AlertLevel, AlertState
from netmon.domain.nodes import DeviceFactory, Group
from netmon.domain.repositories import Repository
from netmon.domain.sensors import SensorFactory
from netmon.domain.status import Status
from . import db as m


def sensor_domain(row):
    obj = SensorFactory.create(row.sensor_type, id=row.id, device_id=row.device_id,
        name=row.name, target=row.target, interval=row.interval, timeout=row.timeout,
        warning_threshold=row.warning_threshold, down_after=row.down_after,
        params=row.params, paused=row.paused)
    obj._status = Status(row.status)
    return obj


class SqlRepository(Repository):
    def __init__(self, db):
        self.db = db

    def get(self, id):
        with self.db.session() as s:
            row = s.get(self.model, id)
            return self.decode(s, row) if row else None

    def list(self):
        with self.db.session() as s:
            return [self.decode(s, r) for r in s.scalars(select(self.model)).all()]

    def add(self, obj):
        data = self.encode(obj)
        with self.db.session() as s:
            row = self.model(**data)
            if obj.id is not None:
                row.id = obj.id
            s.add(row)
            s.flush()
            obj.id = row.id
        return obj

    def update(self, obj):
        data = self.encode(obj)
        with self.db.session() as s:
            row = s.get(self.model, obj.id)
            if row is None:
                raise KeyError(obj.id)
            for k, v in data.items():
                setattr(row, k, v)
        return obj

    def delete(self, id):
        with self.db.session() as s:
            row = s.get(self.model, id)
            if row:
                s.delete(row)


class SqlSensorRepository(SqlRepository):
    model = m.Sensor

    def decode(self, s, row):
        return sensor_domain(row)

    def encode(self, obj):
        return {"device_id": obj.device_id, "sensor_type": obj.type_name,
                **{k: getattr(obj, k) for k in ("name", "target", "interval", "timeout", "warning_threshold", "down_after", "params", "paused")},
                "status": obj.status.value}


class SqlDeviceRepository(SqlRepository):
    model = m.Device

    def decode(self, s, row):
        obj = DeviceFactory.create(row.device_type, id=row.id, name=row.name, ip=row.ip,
            mac=row.mac, vendor=row.vendor, location=row.location, notes=row.notes, extra=row.extra)
        obj.sensors = [sensor_domain(r) for r in s.scalars(select(m.Sensor).where(m.Sensor.device_id == row.id))]
        if row.group_id:
            group = s.get(m.Group, row.group_id)
            Group(group.id, group.name).add(obj)
        return obj

    def encode(self, obj):
        return {**{k: getattr(obj, k) for k in ("name", "ip", "mac", "vendor", "location", "notes", "extra")},
                "device_type": obj.device_type, "group_id": obj.parent.id if obj.parent else None}


class SqlGroupRepository(SqlRepository):
    model = m.Group

    def decode(self, s, row):
        groups = {r.id: Group(r.id, r.name) for r in s.scalars(select(m.Group))}
        for r in s.scalars(select(m.Group)):
            if r.parent_id:
                groups[r.parent_id].add(groups[r.id])
        devices = SqlDeviceRepository(self.db)
        for r in s.scalars(select(m.Device).where(m.Device.group_id.is_not(None))):
            groups[r.group_id].add(devices.decode(s, r))
        return groups[row.id]

    def encode(self, obj):
        return {"name": obj.name, "parent_id": obj.parent.id if obj.parent else None}


class SqlAlertRepository(SqlRepository):
    model = m.Alert

    def __init__(self, db):
        super().__init__(db)
        self.context = local()

    def decode(self, s, r):
        obj = Alert(r.sensor_id, r.device_id, AlertLevel(r.level), r.message,
            Status(r.new_status), r.sensor_name, id=r.id, state=AlertState(r.state),
            created_at=r.opened_at, acked_by=r.ack_by, ack_note=r.ack_note,
            acked_at=r.ack_at, resolved_at=r.resolved_at)
        obj.old_status = r.old_status
        obj.device_name = r.device_name
        return obj

    def encode(self, obj):
        with self.db.session() as s:
            device = s.get(m.Device, obj.device_id) if obj.device_id else None
            name = device.name if device else getattr(obj, "device_name", "")
        return dict(sensor_id=obj.sensor_id, device_id=obj.device_id, device_name=name,
            sensor_name=obj.sensor_name, level=obj.level.value, message=obj.message,
            state=obj.state.value, new_status=obj.status.value,
            old_status=getattr(obj, "old_status", getattr(self.context, "old_status", "UNKNOWN")), opened_at=obj.created_at,
            ack_by=obj.acked_by, ack_note=obj.ack_note, ack_at=obj.acked_at, resolved_at=obj.resolved_at)
