"""Concrete sensor tests with mocked subprocess / sockets / urllib / pysnmp."""
from __future__ import annotations

import socket
import subprocess
import urllib.error
from unittest import mock

import pytest

from netmon.domain.sensors import DnsSensor, HttpSensor, PingSensor, PortSensor, SnmpSensor
from netmon.domain.sensors import ping as ping_mod
from netmon.domain.sensors import snmp as snmp_mod
from netmon.domain.sensors.ping import parse_ping_output
from netmon.domain.status import Status

WIN_EN = """Pinging 10.0.0.1 with 32 bytes of data:
Reply from 10.0.0.1: bytes=32 time=12ms TTL=64
Reply from 10.0.0.1: bytes=32 time=14ms TTL=64
Ping statistics for 10.0.0.1:
    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 12ms, Maximum = 14ms, Average = 13ms
"""
WIN_VI = """Đang ping 10.0.0.1 với 32 byte dữ liệu:
Trả lời từ 10.0.0.1: byte=32 thời gian<1ms TTL=128
Thống kê Ping cho 10.0.0.1:
    Gói: Đã gửi = 4, Đã nhận = 3, Mất = 1 (25% mất),
Thời gian khứ hồi xấp xỉ tính bằng mili giây:
    Tối thiểu = 0ms, Tối đa = 2ms, Trung bình = 1ms
"""
WIN_DOWN = """Pinging 10.0.0.1 with 32 bytes of data:
Request timed out.
    Packets: Sent = 1, Received = 0, Lost = 1 (100% loss),
"""
LINUX = """PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.
64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=0.512 ms
--- 10.0.0.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 0.400/0.512/0.600/0.050 ms
"""


def kw(**extra):
    return {"id": 1, "device_id": 1, "name": "s", "target": "10.0.0.1", "down_after": 1, **extra}


@pytest.mark.parametrize("text,rtt,loss", [(WIN_EN, 13.0, 0.0), (WIN_VI, 1.0, 25.0),
                                           (LINUX, 0.512, 0.0), (WIN_DOWN, None, 100.0)])
def test_parse_ping_output(text, rtt, loss):
    assert parse_ping_output(text) == (rtt, loss)


def _run_ping(text, platform="win32", **extra):
    proc = subprocess.CompletedProcess([], 0, stdout=text.encode("utf-8"), stderr=b"")
    with mock.patch.object(ping_mod.sys, "platform", platform), \
            mock.patch("subprocess.run", return_value=proc) as run:
        s = PingSensor(**kw(**extra))
        return s.run(), run.call_args[0][0]


def test_ping_up_windows_cmd():
    r, cmd = _run_ping(WIN_EN)
    assert r.status == Status.UP and r.value == 13.0
    assert cmd == ["ping", "-n", "3", "-w", "5000", "10.0.0.1"]


def test_ping_linux_cmd_and_threshold():
    r, cmd = _run_ping(LINUX, platform="linux", warning_threshold=0.1)
    assert cmd[:3] == ["ping", "-c", "3"] and r.status == Status.WARNING


def test_ping_loss_warning_and_down():
    assert _run_ping(WIN_VI)[0].status == Status.WARNING  # 25% > 20%
    assert _run_ping(WIN_DOWN)[0].status == Status.DOWN


def test_ping_timeout_and_oserror():
    s = PingSensor(**kw())
    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ping", 1)):
        assert s.run().status == Status.DOWN
    with mock.patch("subprocess.run", side_effect=FileNotFoundError("no ping")):
        assert s.run().status == Status.UNKNOWN


def test_port_sensor():
    s = PortSensor(**kw(params={"port": 22}))
    with mock.patch("socket.create_connection") as cc:
        r = s.run()
    assert r.status == Status.UP and cc.call_args[0][0] == ("10.0.0.1", 22)
    with mock.patch("socket.create_connection", side_effect=ConnectionRefusedError("refused")):
        assert s.run().status == Status.DOWN
    assert PortSensor(**kw(params={"port": 0})).run().status == Status.UNKNOWN


def _resp(code, body=b"hello world"):
    r = mock.MagicMock()
    r.__enter__.return_value.status = code
    r.__enter__.return_value.read.return_value = body
    return r


def test_http_sensor():
    s = HttpSensor(**kw(target="http://x/", params={"contains": "world"}))
    with mock.patch("urllib.request.urlopen", return_value=_resp(200)):
        assert s.run().status == Status.UP
    with mock.patch("urllib.request.urlopen", return_value=_resp(200, b"nope")):
        assert "missing" in s.run().message
    with mock.patch("urllib.request.urlopen", return_value=_resp(302)):
        s.params = {}
        assert s.run().status == Status.UP
    err = urllib.error.HTTPError("http://x/", 503, "down", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=err):
        r = s.run()
        assert r.status == Status.DOWN and "503" in r.message
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert s.run().status == Status.DOWN


def test_http_target_scheme():
    with mock.patch("urllib.request.urlopen", return_value=_resp(200)) as uo:
        HttpSensor(**kw(target="example.com")).run()
    assert uo.call_args[0][0] == "http://example.com"
    assert HttpSensor(**kw(target="ftp://x")).run().status == Status.UNKNOWN


def test_http_warning_threshold():
    s = HttpSensor(**kw(target="http://x/", warning_threshold=0))
    with mock.patch("urllib.request.urlopen", return_value=_resp(200)), \
            mock.patch.object(HttpSensor, "_elapsed_ms", return_value=50.0):
        assert s.run().status == Status.WARNING


def test_dns_sensor():
    infos = [(socket.AF_INET, 0, 0, "", ("1.2.3.4", 0))]
    s = DnsSensor(**kw(target="example.com"))
    with mock.patch("socket.getaddrinfo", return_value=infos):
        assert s.run().status == Status.UP
        s.params = {"expected_ip": "9.9.9.9"}
        assert s.run().status == Status.DOWN
    with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror("nx")):
        assert s.run().status == Status.DOWN


def test_snmp_sensor():
    s = SnmpSensor(**kw())
    assert s.params["oid"] == snmp_mod.SYS_UPTIME
    with mock.patch.object(snmp_mod, "_snmp_get", return_value="12345"):
        r = s.run()
        assert r.status == Status.UP and r.value == 12345.0
    with mock.patch.object(snmp_mod, "_snmp_get", return_value="up(1)"):
        assert s.run().value is None
    with mock.patch.object(snmp_mod, "_snmp_get", side_effect=ImportError):
        assert s.run().status == Status.UNKNOWN
    with mock.patch.object(snmp_mod, "_snmp_get", side_effect=RuntimeError("timeout")):
        assert s.run().status == Status.DOWN


def test_snmp_real_lib_unreachable():
    """Exercise real pysnmp path against a closed local port (fast timeout)."""
    pytest.importorskip("pysnmp")
    r = SnmpSensor(**kw(target="127.0.0.1", timeout=0.3, params={"port": 1})).run()
    assert r.status in (Status.DOWN, Status.UP)
