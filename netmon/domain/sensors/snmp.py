"""SnmpSensor: SNMP GET of a configured OID via pysnmp (lazy import, FR-34)."""
from __future__ import annotations

import asyncio

from netmon.domain.sensors.base import Sensor, SensorFactory
from netmon.domain.status import CheckResult, Status

SYS_UPTIME = "1.3.6.1.2.1.1.3.0"


def _snmp_get(host: str, port: int, community: str, oid: str, timeout: float) -> str:
    """Return value as string; raise RuntimeError on SNMP error. ImportError if pysnmp missing."""
    from pysnmp.hlapi.v3arch.asyncio import (  # lazy: optional dependency
        CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget, get_cmd)

    async def go() -> str:
        target = await UdpTransportTarget.create((host, port), timeout=timeout, retries=0)
        err_ind, err_stat, err_idx, binds = await get_cmd(
            SnmpEngine(), CommunityData(community, mpModel=1), target, ContextData(),
            ObjectType(ObjectIdentity(oid)))
        if err_ind:
            raise RuntimeError(str(err_ind))
        if err_stat:
            raise RuntimeError(err_stat.prettyPrint())
        return binds[0][1].prettyPrint()

    return asyncio.run(go())


@SensorFactory.register("snmp")
class SnmpSensor(Sensor):
    params_schema = {
        "oid": {"label": "OID", "type": "str", "default": SYS_UPTIME},
        "community": {"label": "Community", "type": "str", "default": "public"},
        "port": {"label": "Port", "type": "int", "default": 161},
    }

    def check(self) -> CheckResult:
        p = self.params
        try:
            raw = _snmp_get(self.target, int(p["port"]), p["community"], p["oid"], self.timeout)
        except ImportError:
            return CheckResult(Status.UNKNOWN, None, "pysnmp not installed")
        except Exception as exc:
            return CheckResult(Status.DOWN, None, f"SNMP error: {exc}")
        try:
            value: float | None = float(raw)
        except ValueError:
            value = None
        return CheckResult(Status.UP, value, f"{p['oid']} = {raw}")
