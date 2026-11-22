from sqlalchemy import select
from netmon.infra.db import Setting
from .errors import ValidationError


class SettingsService:
    defaults = {"default_interval": 30, "down_after": 3, "retention_days": 30, "backup_hour": 2}
    limits = {"default_interval": (10, 3600), "down_after": (1, 100), "retention_days": (1, 3650), "backup_hour": (0, 23)}

    def __init__(self, db, audit):
        self.db, self.audit = db, audit

    def get(self, key=None):
        with self.db.session() as s:
            values = {**self.defaults, **{r.key: r.value for r in s.scalars(select(Setting))}}
        return values[key] if key else values

    def set(self, values, actor=None):
        parsed = {}
        for k, v in values.items():
            try:
                lo, hi = self.limits[k]
                value = int(v)
                if not lo <= value <= hi:
                    raise ValueError()
                parsed[k] = value
            except (ValueError, TypeError, KeyError):
                raise ValidationError({k: "Giá trị không hợp lệ"}) from None
        with self.db.session() as s:
            for k, v in parsed.items():
                s.merge(Setting(key=k, value=v))
        self.audit.log(actor, "settings_update", "settings", parsed)
        return self.get()
