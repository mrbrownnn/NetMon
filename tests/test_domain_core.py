"""Domain tests: status, nodes (TC-05), sensor template, alerts (TC-08/09/11), factory (TC-15), scheduler."""
from __future__ import annotations

import logging
from unittest import mock

import pytest

from netmon.domain.alerts import (Alert, AlertLevel, AlertManager, AlertState, EmailNotifier, LogNotifier,
                                  Notifier, TelegramNotifier, WebNotifier)
from netmon.domain.nodes import DeviceFactory, Group, PC, Printer, Router, Server, Switch
from netmon.domain.repositories import InMemoryRepository
from netmon.domain.scheduler import MonitorScheduler
from netmon.domain.sensors import Sensor, SensorFactory
from netmon.domain.status import CheckResult, Status, worst


class FakeSensor(Sensor):
    """Sensor whose next check results come from a list."""

    def __init__(self, *a, results=None, **kw):
        kw.setdefault("id", 1)
        kw.setdefault("device_id", 1)
        kw.setdefault("name", "fake")
        kw.setdefault("target", "10.0.0.1")
        super().__init__(*a, **kw)
        self.next = Status.UP
        self.value = 1.0

    def check(self) -> CheckResult:
        if isinstance(self.next, Exception):
            raise self.next
        return CheckResult(self.next, self.value, f"is {self.next.value}")


# ---------- status ----------
def test_worst():
    assert worst([]) == Status.UNKNOWN
    assert worst([Status.PAUSED, Status.PAUSED]) == Status.PAUSED
    assert worst([Status.UP, Status.PAUSED]) == Status.UP
    assert worst([Status.UP, Status.WARNING, Status.UNKNOWN]) == Status.WARNING
    assert worst([Status.DOWN, Status.UP]) == Status.DOWN


# ---------- nodes ----------
def _device(cls, ip, status):
    d = cls(id=None, name=f"d{ip}", ip=ip)
    s = FakeSensor(down_after=1)
    s.next = status
    s.run()
    d.sensors.append(s)
    return d


def test_tc05_group_status_worst_child():
    a = Group(1, "A")
    for i in range(3):
        a.add(_device(PC, f"10.0.0.{i + 1}", Status.UP))
    a.add(_device(Router, "10.0.0.9", Status.DOWN))
    assert a.status == Status.DOWN
    root = Group(2, "root")
    root.add(a)
    assert root.status == Status.DOWN  # recursive


def test_group_cycle_and_move():
    a, b = Group(1, "A"), Group(2, "B", parent=None)
    a.add(b)
    c = Group(3, "C", parent=b)
    assert a.is_ancestor_of(c) and not c.is_ancestor_of(a)
    with pytest.raises(ValueError):
        c.add(a)
    with pytest.raises(ValueError):
        a.add(a)
    a.add(c)  # move from b to a
    assert c.parent is a and c not in b.children
    a.remove(c)
    assert c.parent is None


def test_device_ip_validation_and_extra():
    with pytest.raises(ValueError):
        Router(id=1, name="r", ip="300.1.1.1")
    with pytest.raises(ValueError):
        Router(id=1, name="", ip="1.1.1.1")
    r = Router(id=1, name="r", ip=" 192.168.1.1 ", extra={"interfaces": 4})
    assert r.ip == "192.168.1.1" and r.extra["interfaces"] == 4
    assert Switch(id=2, name="s", ip="1.1.1.2").extra == {"ports": 0, "vlans": ""}


def test_default_sensors_fr12():
    ip = "10.1.1.1"
    types = lambda cls: [d["type"] for d in cls(id=1, name="x", ip=ip).default_sensors()]  # noqa: E731
    assert types(Router) == types(Switch) == ["ping", "port"]
    assert Router(id=1, name="x", ip=ip).default_sensors()[1]["params"] == {"port": 22}
    assert types(Server) == ["ping", "http"]
    assert types(PC) == types(Printer) == ["ping"]


def test_device_factory():
    assert set(DeviceFactory.types()) >= {"router", "switch", "server", "pc", "printer"}
    d = DeviceFactory.create("server", id=None, name="srv", ip="10.0.0.5")
    assert isinstance(d, Server) and d.device_type == "server"
    with pytest.raises(ValueError):
        DeviceFactory.create("toaster", id=None, name="t", ip="1.1.1.1")


def test_device_pause_resume_cascades():
    g = Group(1, "g")
    d = _device(PC, "10.0.0.1", Status.UP)
    g.add(d)
    g.pause()
    assert d.status == Status.PAUSED and g.status == Status.PAUSED
    g.resume()
    assert d.sensors[0].status == Status.UNKNOWN


# ---------- sensor base ----------
@pytest.mark.parametrize("kw", [{"interval": 9}, {"interval": 3601}, {"timeout": 0},
                                {"down_after": 0}, {"warning_threshold": -1}, {"name": " "}, {"target": ""}])
def test_sensor_validation(kw):
    with pytest.raises(ValueError):
        FakeSensor(**kw)


def test_sensor_threshold_and_down_after():
    s = FakeSensor(warning_threshold=100, down_after=3)
    s.run()
    assert s.status == Status.UP
    s.value = 150
    assert s.run().status == Status.WARNING
    s.next = Status.DOWN
    r1 = s.run()
    assert s.status == Status.WARNING and "fail 1/3" in r1.message and s.consecutive_failures == 1
    s.run()
    assert s.status == Status.WARNING
    s.run()
    assert s.status == Status.DOWN and s.last_result.status == Status.DOWN
    s.next, s.value = Status.UP, 1
    s.run()
    assert s.status == Status.UP and s.consecutive_failures == 0


def test_sensor_check_exception_gives_unknown():
    s = FakeSensor()
    s.next = RuntimeError("boom")
    r = s.run()
    assert r.status == Status.UNKNOWN and "boom" in r.message


def test_observer_events_and_bad_observer():
    s = FakeSensor(down_after=1)
    obs = mock.Mock()
    bad = mock.Mock()
    bad.on_result.side_effect = RuntimeError("x")
    s.attach(obs)
    s.attach(obs)  # no duplicate
    s.attach(bad)
    s.run()
    s.run()
    assert obs.on_status_changed.call_count == 1 and obs.on_result.call_count == 2
    s.detach(obs)
    s.next = Status.DOWN
    s.run()
    assert obs.on_status_changed.call_count == 1


# ---------- alerts ----------
@pytest.fixture
def mgr():
    return AlertManager(InMemoryRepository())


def test_tc08_no_new_alert_while_down(mgr):
    s = FakeSensor(down_after=1)
    s.attach(mgr)
    s.run()  # UNKNOWN -> UP: no alert
    assert mgr.repository.list() == []
    s.next = Status.DOWN
    for _ in range(6):
        s.run()
    alerts = mgr.repository.list()
    assert len(alerts) == 1 and alerts[0].level == AlertLevel.CRITICAL and alerts[0].state == AlertState.OPEN


def test_tc09_recovery_resolves(mgr):
    events = []
    mgr.on_change = lambda e, a: events.append(e)
    s = FakeSensor(down_after=1)
    s.attach(mgr)
    s.run()
    s.next = Status.DOWN
    s.run()
    mgr.acknowledge(mgr.open_alerts()[0].id, "admin", "on it")
    s.next = Status.UP
    s.run()
    assert s.status == Status.UP and mgr.open_alerts() == []
    down, up = mgr.repository.list()
    assert down.state == AlertState.RESOLVED and down.resolved_at and down.acked_by == "admin"
    assert up.level == AlertLevel.INFO
    assert events == ["alert_opened", "alert_updated", "alert_updated", "alert_opened"]


def test_warning_to_down_supersedes(mgr):
    s = FakeSensor(down_after=1)
    s.attach(mgr)
    s.run()
    s.next = Status.WARNING
    s.run()
    s.next = Status.DOWN
    s.run()
    opened = mgr.open_alerts(s.id)
    assert len(opened) == 1 and opened[0].level == AlertLevel.CRITICAL


def test_tc11_paused_group_no_alert(mgr):
    g = Group(1, "g")
    d = _device(PC, "10.0.0.1", Status.UP)
    d.sensors[0].attach(mgr)
    g.add(d)
    g.pause()
    d.sensors[0].next = Status.DOWN
    for _ in range(5):
        assert d.sensors[0].run().status == Status.PAUSED
    assert g.status == Status.PAUSED and mgr.repository.list() == []
    g.resume()  # resume -> UNKNOWN, then UP: still no alert
    d.sensors[0].next = Status.UP
    d.sensors[0].run()
    assert mgr.repository.list() == []


def test_alert_ack_rules():
    a = Alert(1, 1, AlertLevel.WARNING, "m", Status.WARNING)
    a.ack("bob", "n")
    assert a.state == AlertState.ACKNOWLEDGED and a.to_dict()["acked_by"] == "bob"
    a.resolve()
    with pytest.raises(ValueError):
        a.ack("bob")
    with pytest.raises(KeyError):
        AlertManager().acknowledge(99, "x")


def test_dispatch_isolates_failing_notifier(mgr, caplog):
    class Broken(Notifier):
        name = "broken"

        def send(self, alert):
            raise RuntimeError("smtp down")

    sent = []
    web = WebNotifier(lambda e, d: sent.append(e))
    off = WebNotifier(lambda e, d: sent.append("off"), enabled=False)
    mgr.notifiers = [Broken(), web, off, LogNotifier()]
    with caplog.at_level(logging.INFO):
        res = mgr.dispatch(Alert(1, 1, AlertLevel.CRITICAL, "m", Status.DOWN, "ping"))
    assert res == {"broken": "error: notification failed", "web": "ok", "log": "ok"}
    assert sent == ["alert_opened"] and "notifier broken failed" in caplog.text


def test_email_notifier():
    n = EmailNotifier("smtp.x", 587, "a@x", ["b@x"], "u", "p")
    with mock.patch("smtplib.SMTP") as smtp:
        n.send_test()
    conn = smtp.return_value.__enter__.return_value
    conn.starttls.assert_called_once()
    conn.login.assert_called_once_with("u", "p")
    conn.send_message.assert_called_once()
    with pytest.raises(ValueError):
        EmailNotifier("h").send_test()


def test_telegram_notifier():
    n = TelegramNotifier("TOKEN", "42")
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = b'{"ok": true}'
    with mock.patch("urllib.request.urlopen", return_value=resp) as uo:
        n.send_test()
    assert "botTOKEN/sendMessage" in uo.call_args[0][0] and b"chat_id=42" in uo.call_args[1]["data"]
    resp.__enter__.return_value.read.return_value = b'{"ok": false, "description": "bad"}'
    with mock.patch("urllib.request.urlopen", return_value=resp), pytest.raises(RuntimeError, match="bad"):
        n.send_test()


# ---------- factory TC-15 ----------
def test_tc15_new_sensor_registered_without_editing_old_files():
    @SensorFactory.register("icmp_jitter")
    class IcmpJitterSensor(Sensor):
        params_schema = {"samples": {"label": "Samples", "type": "int", "default": 5}}

        def check(self):
            return CheckResult(Status.UP, 0.5, "jitter")

    assert SensorFactory.types()["icmp_jitter"] is IcmpJitterSensor
    s = SensorFactory.create("icmp_jitter", id=7, device_id=1, name="j", target="1.1.1.1")
    assert s.type_name == "icmp_jitter" and s.params == {"samples": 5} and s.run().status == Status.UP
    assert {"ping", "port", "http", "dns", "snmp"} <= set(SensorFactory.types())
    with pytest.raises(ValueError):
        SensorFactory.create("nope")


# ---------- repository ----------
def test_inmemory_repository():
    repo = InMemoryRepository()
    a = repo.add(Alert(1, 1, AlertLevel.INFO, "m", Status.UP))
    assert a.id == 1 and repo.get(1) is a and repo.list() == [a]
    with pytest.raises(ValueError):
        repo.add(a)
    repo.update(a)
    repo.delete(1)
    assert repo.get(1) is None
    with pytest.raises(KeyError):
        repo.update(a)


# ---------- scheduler ----------
@pytest.fixture
def sched():
    MonitorScheduler.reset_instance()
    clock = [0.0]
    sch = MonitorScheduler(max_workers=2, clock=lambda: clock[0])
    sch.clock = clock
    yield sch
    MonitorScheduler.reset_instance()


def test_scheduler_singleton(sched):
    assert MonitorScheduler() is sched is MonitorScheduler.instance()


def test_scheduler_runs_by_interval_and_isolates_errors(sched):
    good, bad = FakeSensor(id=1, interval=10), FakeSensor(id=2, interval=20)
    bad.next = RuntimeError("boom")
    sched.add_sensor(good)
    sched.add_sensor(bad)
    with pytest.raises(ValueError):
        sched.add_sensor(FakeSensor(id=None))
    with mock.patch.object(good, "run", wraps=good.run) as g, mock.patch.object(bad, "run", wraps=bad.run) as b:
        sched.tick()                       # t=0: both run
        sched.clock[0] = 10; sched.tick()  # noqa: E702  t=10: good only
        sched.clock[0] = 20; sched.tick()  # noqa: E702  t=20: both
    assert g.call_count == 3 and b.call_count == 2
    assert bad.status == Status.UNKNOWN and good.status == Status.UP


def test_scheduler_run_raises_is_contained(sched):
    s = FakeSensor(id=1)
    sched.add_sensor(s)
    with mock.patch.object(s, "run", side_effect=RuntimeError("observer exploded")):
        assert sched.run_now(1).status == Status.UNKNOWN


def test_scheduler_remove_reschedule_run_now(sched):
    s = FakeSensor(id=1, interval=10)
    sched.add_sensor(s, run_immediately=False)
    assert sched.get_sensor(1) is s and sched.run_now(1).status == Status.UP
    s.interval = 60
    sched.reschedule(1)
    sched.clock[0] = 10
    with mock.patch.object(s, "run") as r:
        sched.tick()
        r.assert_not_called()
        sched.clock[0] = 60
        sched.tick()
        r.assert_called_once()
    sched.remove_sensor(1)
    with pytest.raises(KeyError):
        sched.run_now(1)
    with pytest.raises(KeyError):
        sched.reschedule(1)
    assert sched.stats() == {"running": False, "sensor_count": 0, "threads": 0, "in_flight": 0}


def test_scheduler_threaded_start_stop():
    MonitorScheduler.reset_instance()
    import threading
    done = threading.Event()
    sch = MonitorScheduler(max_workers=2)
    s = FakeSensor(id=1)
    s.attach(mock.Mock(on_result=lambda *_: done.set()))
    sch.add_sensor(s)
    sch.start()
    sch.start()  # idempotent
    assert done.wait(3)
    st = sch.stats()
    assert st["running"] and st["threads"] == 2 and st["sensor_count"] == 1
    MonitorScheduler.reset_instance()
    assert not sch.running
