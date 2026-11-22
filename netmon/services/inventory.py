"""Inventory trees, validated CRUD and CSV interchange."""
import csv
import io
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from netmon.domain.nodes import DeviceFactory
from netmon.domain.status import Status, worst
from netmon.infra import db as m
from netmon.infra.repositories import SqlDeviceRepository
from .common import paginate, require, row_dict
from .errors import ValidationError


class InventoryService:
    def __init__(self, db, audit):
        self.db, self.audit = db, audit
        self.monitor = None
        self.repository = SqlDeviceRepository(db)

    def device_types(self):
        return [{"type": k, "name": c.__name__, "extra_fields": c.extra_fields}
                for k, c in DeviceFactory.types().items()]

    def descendant_ids(self, group_id):
        with self.db.session() as s:
            require(s, m.Group, int(group_id))
            rows = list(s.scalars(select(m.Group)))
        ids = {int(group_id)}
        while True:
            children = {r.id for r in rows if r.parent_id in ids}
            if children <= ids:
                return ids
            ids |= children

    def ancestor_ids(self, group_id):
        with self.db.session() as s:
            parents = {g.id: g.parent_id for g in s.scalars(select(m.Group))}
        ids = []
        while group_id is not None:
            ids.append(group_id)
            group_id = parents.get(group_id)
        return ids

    def groups_tree(self):
        with self.db.session() as s:
            rows = [row_dict(g) for g in s.scalars(select(m.Group).order_by(m.Group.name))]
        devices = self.list_devices(paginated=False)
        nodes = {r["id"]: {**r, "children": [], "devices": []} for r in rows}
        roots = []
        for node in nodes.values():
            (nodes[node["parent_id"]]["children"] if node["parent_id"] in nodes else roots).append(node)
        for d in devices:
            if d["group_id"] in nodes:
                nodes[d["group_id"]]["devices"].append(d)
        def compute(node):
            for child in node["children"]:
                compute(child)
            states = [Status(d["status"]) for d in node["devices"]] + [Status(c["status"]) for c in node["children"]]
            node["status"] = worst(states).value
            counts = {st.value: sum(d["status"] == st.value for d in node["devices"]) for st in Status}
            for child in node["children"]:
                for st in Status:
                    counts[st.value] += child["counts"][st.value]
            counts["total"] = sum(counts.values())
            node["counts"], node["device_count"] = counts, counts["total"]
        for root in roots:
            compute(root)
        return roots

    def create_group(self, name, parent_id=None, actor=None):
        if not str(name or "").strip():
            raise ValidationError({"name": "Tên không được trống"})
        with self.db.session() as s:
            if parent_id is not None:
                require(s, m.Group, parent_id)
            row = m.Group(name=str(name).strip(), parent_id=parent_id)
            s.add(row)
            s.flush()
            result = row_dict(row)
        self.audit.log(actor, "group_create", result["id"])
        return result

    def rename_group(self, group_id, name, actor=None):
        if not str(name or "").strip():
            raise ValidationError({"name": "Tên không được trống"})
        with self.db.session() as s:
            row = require(s, m.Group, group_id)
            row.name = str(name).strip()
            result = row_dict(row)
        self.audit.log(actor, "group_rename", group_id)
        return result

    def move_group(self, group_id, parent_id, actor=None):
        ids = self.descendant_ids(group_id)
        if parent_id is not None and int(parent_id) in ids:
            raise ValidationError({"parent_id": "Không thể tạo vòng nhóm"})
        with self.db.session() as s:
            if parent_id is not None:
                require(s, m.Group, parent_id)
            row = require(s, m.Group, group_id)
            row.parent_id = parent_id
            result = row_dict(row)
        self.audit.log(actor, "group_move", group_id, {"parent_id": parent_id})
        return result

    def delete_group(self, group_id, actor=None):
        ids = self.descendant_ids(group_id)
        with self.db.session() as s:
            if s.scalar(select(m.Device.id).where(m.Device.group_id.in_(ids)).limit(1)):
                raise ValidationError({"group_id": "Nhóm còn thiết bị"})
            s.delete(require(s, m.Group, group_id))
        self.audit.log(actor, "group_delete", group_id)
        return {"ok": True}

    def list_devices(self, q=None, type=None, group=None, status=None, sort="name", order="asc", page=1, paginated=True):
        group_ids = self.descendant_ids(group) if group not in (None, "") else None
        with self.db.session() as s:
            sensors = list(s.scalars(select(m.Sensor)))
            rows = [row_dict(r) for r in s.scalars(select(m.Device))]
        by_device = {}
        for sensor in sensors:
            by_device.setdefault(sensor.device_id, []).append(Status(sensor.status))
        items = []
        for d in rows:
            d["status"] = worst(by_device.get(d["id"], [])).value
            d["sensor_count"] = len(by_device.get(d["id"], []))
            if q and not any(str(q).casefold() in str(d[k]).casefold() for k in ("name", "ip", "mac")):
                continue
            if type and d["device_type"] != type:
                continue
            if group_ids is not None and d["group_id"] not in group_ids:
                continue
            if status and d["status"] != str(status).upper():
                continue
            items.append(d)
        if sort not in ("name", "ip", "device_type", "status", "location", "vendor"):
            raise ValidationError({"sort": "Cột không hợp lệ"})
        items.sort(key=lambda d: tuple(map(int, d["ip"].split("."))) if sort == "ip" else str(d[sort]).casefold(), reverse=order == "desc")
        return paginate(items, page) if paginated else items

    def get_device(self, device_id):
        with self.db.session() as s:
            result = row_dict(require(s, m.Device, device_id))
            result["sensors"] = [row_dict(r) for r in s.scalars(select(m.Sensor).where(m.Sensor.device_id == device_id))]
            cred = s.scalar(select(m.Credential).where(m.Credential.device_id == device_id))
            result["credential"] = row_dict(cred, ("password_enc",)) if cred else None
        result["status"] = worst(Status(r["status"]) for r in result["sensors"]).value
        return result

    def _validate(self, data, device_id=None):
        errors = {}
        kind = data.get("device_type", data.get("type", "pc"))
        name, ip = str(data.get("name") or "").strip(), str(data.get("ip") or "").strip()
        if not name:
            errors["name"] = "Tên không được trống"
        if kind not in DeviceFactory.types():
            errors["device_type"] = "Loại không hợp lệ"
        import ipaddress
        try:
            ip = str(ipaddress.IPv4Address(ip))
        except ValueError:
            errors["ip"] = "IPv4 không hợp lệ"
        with self.db.session() as s:
            for field, value in (("name", name), ("ip", ip)):
                query = select(m.Device.id).where(getattr(m.Device, field) == value)
                if device_id:
                    query = query.where(m.Device.id != device_id)
                if s.scalar(query):
                    errors[field] = "Giá trị đã tồn tại"
            if data.get("group_id") is not None and not s.get(m.Group, data["group_id"]):
                errors["group_id"] = "Nhóm không tồn tại"
        extra = data.get("extra") or {}
        if not isinstance(extra, dict):
            errors["extra"] = "Thuộc tính phải là đối tượng"
        elif kind in DeviceFactory.types():
            extra = dict(extra)
            for key, spec in DeviceFactory.types()[kind].extra_fields.items():
                value = extra.get(key, spec.get("default"))
                try:
                    extra[key] = int(value) if spec["type"] == "int" else str(value)
                    if spec["type"] == "int" and extra[key] < 0:
                        raise ValueError()
                except (ValueError, TypeError):
                    errors[f"extra.{key}"] = "Giá trị không hợp lệ"
        if errors:
            raise ValidationError(errors)
        return DeviceFactory.create(kind, id=device_id, name=name, ip=ip, extra=extra,
            **{k: str(data.get(k) or "") for k in ("mac", "vendor", "location", "notes")})

    def create_device(self, data, actor=None, default_sensors=None):
        device = self._validate(data)
        selected = default_sensors if default_sensors is not None else data.get("default_sensors")
        defaults = device.default_sensors()
        if selected is not None:
            defaults = [v for i, v in enumerate(defaults) if v["type"] in selected or v["name"] in selected or i in selected]
        objects = [self.monitor.build_sensor({**item, "device_id": 0}) for item in defaults]
        try:
            with self.db.session() as s:
                row = m.Device(**self.repository.encode(device))
                row.group_id = data.get("group_id")
                s.add(row)
                s.flush()
                for obj in objects:
                    obj.device_id = row.id
                    sensor_row = m.Sensor(**self.monitor.repository.encode(obj))
                    s.add(sensor_row)
                    s.flush()
                    obj.id = sensor_row.id
                device.id = row.id
        except IntegrityError:
            raise ValidationError({"name": "Tên hoặc IP đã tồn tại"}) from None
        for obj in objects:
            self.monitor.register(obj)
        self.audit.log(actor, "device_create", device.id)
        return self.get_device(device.id)

    def update_device(self, device_id, data, actor=None):
        current = self.get_device(device_id)
        merged = {**current, **data}
        if "type" in data and "device_type" not in data:
            merged["device_type"] = data["type"]
        device = self._validate(merged, device_id)
        try:
            with self.db.session() as s:
                row = require(s, m.Device, device_id)
                for k, v in self.repository.encode(device).items():
                    if k != "group_id":
                        setattr(row, k, v)
                row.group_id = merged.get("group_id")
        except IntegrityError:
            raise ValidationError({"name": "Tên hoặc IP đã tồn tại"}) from None
        self.audit.log(actor, "device_update", device_id)
        return self.get_device(device_id)

    def move_device(self, device_id, group_id, actor=None):
        return self.update_device(device_id, {"group_id": group_id}, actor)

    def delete_device(self, device_id, actor=None):
        device = self.get_device(device_id)
        for sensor in device["sensors"]:
            self.monitor.unregister(sensor["id"])
        with self.db.session() as s:
            s.delete(require(s, m.Device, device_id))
        self.audit.log(actor, "device_delete", device_id, {"name": device["name"]})
        return {"ok": True}

    def import_csv(self, content, actor=None):
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content.lstrip("﻿")
        result = {"imported": 0, "errors": []}
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not {"name", "ip"} <= set(reader.fieldnames):
            return {"imported": 0, "errors": [{"line": 1, "msg": "Thiếu cột name/ip"}]}
        for row in reader:
            try:
                if row.get("group_id"):
                    row["group_id"] = int(row["group_id"])
                else:
                    row["group_id"] = None
                row["extra"] = json.loads(row["extra"]) if row.get("extra") else {}
                self.create_device(row, actor)
                result["imported"] += 1
            except (ValueError, KeyError, TypeError) as e:
                result["errors"].append({"line": reader.line_num, "msg": str(e)})
        self.audit.log(actor, "devices_import", "inventory", {"imported": result["imported"]})
        return result

    def export_csv(self, actor=None, **filters):
        filters.pop("paginated", None)
        fields = ["name", "ip", "device_type", "group_id", "mac", "vendor", "location", "notes", "extra"]
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for d in self.list_devices(**filters, paginated=False):
            writer.writerow({k: json.dumps(d[k], ensure_ascii=False) if k == "extra" else d[k] for k in fields})
        self.audit.log(actor, "devices_export", "inventory")
        return out.getvalue()
