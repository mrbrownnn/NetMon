"""Sensors. Importing this package registers all built-in sensor types in SensorFactory."""
from netmon.domain.sensors.base import Sensor, SensorFactory, SensorObserver
from netmon.domain.sensors.dns import DnsSensor
from netmon.domain.sensors.http import HttpSensor
from netmon.domain.sensors.ping import PingSensor
from netmon.domain.sensors.port import PortSensor
from netmon.domain.sensors.snmp import SnmpSensor

__all__ = ["Sensor", "SensorFactory", "SensorObserver", "PingSensor", "PortSensor",
           "HttpSensor", "DnsSensor", "SnmpSensor"]
