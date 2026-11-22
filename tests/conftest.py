"""Shared DB fixture. Default: SQLite files under tmp_path.
Set NETMON_TEST_DB=postgresql://user:pw@host:port/db to run the same tests on Postgres (schema dropped per test)."""
import os

import pytest
from sqlalchemy import create_engine

from netmon.infra.config import normalize_db_url
from netmon.infra.db import Base

PG = os.getenv("NETMON_TEST_DB")


@pytest.fixture
def db_url(tmp_path):
    def make(name="data.db"):
        if not PG:
            return f"sqlite:///{tmp_path / name}"
        return PG
    if PG:
        engine = create_engine(normalize_db_url(PG))
        Base.metadata.drop_all(engine)
        engine.dispose()
    yield make
    if PG:
        engine = create_engine(normalize_db_url(PG))
        Base.metadata.drop_all(engine)
        engine.dispose()
