"""Interval-based uptime and export data (FR-50..52)."""
import csv
import io
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from xml.sax.saxutils import escape

from sqlalchemy import select
from netmon.infra import db as m
from .common import date, require
from .errors import ValidationError


class ReportService:
    def __init__(self, db, inventory):
        self.db, self.inventory = db, inventory

    def _range(self, from_, to):
        end = date(to) or datetime.now()
        start = date(from_) or end - timedelta(days=1)
        if start >= end:
            raise ValidationError({"from": "Khoảng thời gian không hợp lệ"})
        return start, end

    def _intervals(self, sensor_id, start, end):
        with self.db.session() as s:
            require(s, m.Sensor, sensor_id)
            previous = s.scalar(select(m.CheckResult).where(m.CheckResult.sensor_id == sensor_id,
                m.CheckResult.ts <= start).order_by(m.CheckResult.ts.desc(), m.CheckResult.id.desc()).limit(1))
            rows = list(s.scalars(select(m.CheckResult).where(m.CheckResult.sensor_id == sensor_id,
                m.CheckResult.ts > start, m.CheckResult.ts < end).order_by(m.CheckResult.ts, m.CheckResult.id)))
            points = [(start, previous.status if previous else "UNKNOWN")]
            points += [(r.ts, r.status) for r in rows]
        return [(ts, points[i + 1][0] if i + 1 < len(points) else end, state)
                for i, (ts, state) in enumerate(points)]

    def uptime(self, sensor_id, from_=None, to=None):
        start, end = self._range(from_, to)
        spans = self._intervals(sensor_id, start, end)
        durations = {st: 0.0 for st in ("UP", "WARNING", "DOWN", "PAUSED", "UNKNOWN")}
        down_count, previous = 0, None
        for a, b, status in spans:
            durations[status] += (b - a).total_seconds()
            if status == "DOWN" and previous != "DOWN":
                down_count += 1
            previous = status
        total = (end - start).total_seconds()
        denominator = total - durations["PAUSED"]
        return {"sensor_id": sensor_id, "from": start.isoformat(), "to": end.isoformat(),
            "uptime": round(durations["UP"] / denominator * 100, 4) if denominator else None,
            "total_seconds": total, "durations": durations, "down_count": down_count,
            "total_down_seconds": durations["DOWN"]}

    def latency_series(self, sensor_id, period="24h", from_=None, to=None):
        if period not in ("24h", "7d", "30d"):
            raise ValidationError({"period": "Chọn 24h, 7d hoặc 30d"})
        end = date(to) or datetime.now()
        start = date(from_) or end - timedelta(days={"24h": 1, "7d": 7, "30d": 30}[period])
        start, end = self._range(start, end)
        with self.db.session() as s:
            require(s, m.Sensor, sensor_id)
            rows = list(s.scalars(select(m.CheckResult).where(m.CheckResult.sensor_id == sensor_id,
                m.CheckResult.ts >= start, m.CheckResult.ts <= end).order_by(m.CheckResult.ts)))
            points = [(r.ts, r.value, r.status) for r in rows]
        buckets = {}
        width = (end - start).total_seconds() / 300
        for ts, value, state in points:
            index = min(299, int((ts - start).total_seconds() / width))
            buckets.setdefault(index, []).append((ts, value, state))
        series = []
        for bucket in buckets.values():
            values = [v for _, v, _ in bucket if v is not None]
            series.append({"ts": bucket[0][0].isoformat(), "value": mean(values) if values else None,
                "status": bucket[-1][2]})
        bands = []
        for a, b, status in self._intervals(sensor_id, start, end):
            if status not in ("DOWN", "PAUSED"):
                continue
            if bands and bands[-1]["status"] == status and bands[-1]["to"] == a.isoformat():
                bands[-1]["to"] = b.isoformat()
            else:
                bands.append({"from": a.isoformat(), "to": b.isoformat(), "status": status})
        return {"sensor_id": sensor_id, "from": start.isoformat(), "to": end.isoformat(), "points": series, "bands": bands}

    def device_summary(self, device_id, from_=None, to=None):
        start, end = self._range(from_, to)
        device = self.inventory.get_device(device_id)
        # Device UP only when every active sensor UP; PAUSED only when all paused.
        spans = [self._intervals(sensor["id"], start, end) for sensor in device["sensors"]]
        boundaries = sorted({start, end} | {t for intervals in spans for a, b, _ in intervals for t in (a, b)})
        up = paused = down = 0.0
        down_count = 0
        was_down = False
        for a, b in zip(boundaries, boundaries[1:]):
            states = [next(st for x, y, st in intervals if x <= a < y) for intervals in spans]
            active = [st for st in states if st != "PAUSED"]
            seconds = (b - a).total_seconds()
            is_down = "DOWN" in active
            if states and not active:
                paused += seconds
            elif active and all(st == "UP" for st in active):
                up += seconds
            if is_down:
                down += seconds
                if not was_down:
                    down_count += 1
            was_down = is_down
        sensor_ids = [sensor["id"] for sensor in device["sensors"] if sensor["sensor_type"] != "snmp"]
        with self.db.session() as s:
            values = list(s.scalars(select(m.CheckResult.value).where(m.CheckResult.sensor_id.in_(sensor_ids),
                m.CheckResult.ts >= start, m.CheckResult.ts <= end, m.CheckResult.value.is_not(None))))
        denominator = (end - start).total_seconds() - paused
        return {"device_id": device_id, "name": device["name"], "ip": device["ip"],
            "uptime": round(up / denominator * 100, 4) if denominator else None,
            "down_count": down_count, "total_down_seconds": down,
            "avg_latency": mean(values) if values else None, "max_latency": max(values) if values else None}

    def group_report(self, group=None, from_=None, to=None):
        start, end = self._range(from_, to)
        items = [self.device_summary(d["id"], start, end)
            for d in self.inventory.list_devices(group=group, paginated=False)]
        uptimes = [d["uptime"] for d in items if d["uptime"] is not None]
        return {"group_id": group, "from": start.isoformat(), "to": end.isoformat(),
            "device_count": len(items), "uptime": mean(uptimes) if uptimes else None,
            "down_count": sum(d["down_count"] for d in items),
            "total_down_seconds": sum(d["total_down_seconds"] for d in items), "items": items,
            "top_worst": sorted(items, key=lambda d: (d["uptime"] is None, d["uptime"] or 0, -d["total_down_seconds"]))[:5]}

    def export_csv(self, group=None, from_=None, to=None):
        report = self.group_report(group, from_, to)
        out = io.StringIO(newline="")
        fields = ["device_id", "name", "ip", "uptime", "down_count", "total_down_seconds", "avg_latency", "max_latency"]
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report["items"])
        return out.getvalue()

    def export_pdf(self, group=None, from_=None, to=None):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        report = self.group_report(group, from_, to)
        font = "Helvetica"
        for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
            if Path(path).is_file():
                font = "NetMonUnicode"
                if font not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(font, path))
                break
        style = getSampleStyleSheet()["Normal"]
        style.fontName = font
        buffer = io.BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36)
        rows = [["Thiết bị", "IP", "Uptime %", "Lần DOWN", "DOWN (s)"]]
        for d in report["items"]:
            rows.append([Paragraph(escape(d["name"]), style), d["ip"],
                "—" if d["uptime"] is None else f'{d["uptime"]:.2f}', str(d["down_count"]), f'{d["total_down_seconds"]:.0f}'])
        table = Table(rows, repeatRows=1, colWidths=[175, 90, 75, 65, 65])
        table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.5, "#888888")]))
        document.build([Paragraph("Báo cáo giám sát mạng", style), Spacer(1, 12),
            Paragraph(escape(f'{report["from"]} – {report["to"]}'), style), Spacer(1, 12), table])
        return buffer.getvalue()
