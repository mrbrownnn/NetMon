"""Shared serialization and bounded query helpers."""
from datetime import datetime, timezone
from enum import Enum
from math import ceil


def json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def row_dict(row, exclude=()):
    return {c.name: json_value(getattr(row, c.name)) for c in row.__table__.columns if c.name not in exclude}


def require(session, model, id):
    row = session.get(model, id)
    if row is None:
        raise KeyError(f"{model.__name__} {id}")
    return row


def paginate(items, page=1, per_page=20):
    page = max(1, int(page))
    total = len(items)
    return {"items": items[(page - 1) * per_page:page * per_page], "total": total,
            "page": page, "pages": ceil(total / per_page)}


def date(value):
    if value is None or value == "":
        return None
    d = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
