"""Regression checks for domain review; no live network required."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import pytest

from netmon.domain.alerts import AlertManager, AlertState
from netmon.domain.remote import (CommandError, CommandHistory, FakeConnection, SSHConnection,
                                  SetHostname, DriverFactory, ConnectionError_)
from netmon.domain.scheduler import MonitorScheduler
from netmon.domain.sensors import Sensor, PingSensor, HttpSensor
from netmon.domain.sensors.ping import parse_ping_output
from netmon.domain.status import Status, CheckResult


class Probe(Sensor):
    def __init__(self, **kw):
        super().__init__(1, 1, "probe", "localhost", **kw)
        self.next = Status.UP

    def check(self):
        return CheckResult(self.next, 1)


@pytest.mark.parametrize("intermediate", [Status.UNKNOWN, Status.PAUSED])
def test_recovery_after_unknown_or_pause_resolves_existing_alert(intermediate):
    sensor, manager = Probe(down_after=1), AlertManager()
    sensor.attach(manager)
    sensor.next = Status.DOWN
    sensor.run()
    alert = manager.open_alerts()[0]
    if intermediate == Status.PAUSED:
        sensor.pause()
        sensor.resume()
    else:
        sensor.next = Status.UNKNOWN
        sensor.run()
    sensor.next = Status.UP
    sensor.run()
    assert alert.state == AlertState.RESOLVED
    assert manager.open_alerts() == []


def test_resume_active_sensor_does_not_reset_failure_count_or_emit_alert():
    sensor, manager = Probe(), AlertManager()
    sensor.attach(manager)
    sensor.next = Status.DOWN
    sensor.run()
    sensor.resume()
    assert sensor.consecutive_failures == 1
    sensor.run()
    sensor.run()
    assert sensor.status == Status.DOWN
    sensor.resume()
    sensor.run()
    assert len(manager.repository.list()) == 1


@pytest.mark.parametrize("field,value", [("timeout", float("nan")), ("timeout", float("inf")),
                                         ("warning_threshold", float("nan")),
                                         ("warning_threshold", float("inf"))])
def test_nonfinite_sensor_settings_rejected(field, value):
    with pytest.raises(ValueError):
        Probe(**{field: value})


def test_result_observers_complete_before_pause_event():
    sensor, events = Probe(), []
    sensor.attach(mock.Mock(on_status_changed=lambda s, old, r: events.append(r.status),
                            on_result=lambda s, r: events.append(r.status)))
    sensor.run()
    sensor.pause()
    assert events == [Status.UP, Status.UP, Status.PAUSED]


@pytest.mark.parametrize("driver", ["vyos", "mikrotik", "cisco_ios"])
def test_echo_with_error_hostname_execute_and_undo(driver):
    conn = FakeConnection(driver=driver)
    conn.state["hostname"] = "error-original"
    original = conn.send_config

    def echo(commands):
        output = original(commands)
        return "\n".join([f"error-router# {cmd}" for cmd in commands] + [output, "error-router#"])

    conn.send_config = echo
    history = CommandHistory()
    history.execute(SetHostname(conn.driver, "error-router"), conn)
    history.undo_last(conn)
    assert conn.state["hostname"] == "error-original"
    assert history.items[0].undone


def test_echo_filter_does_not_hide_actual_command_error():
    conn = FakeConnection()
    conn.send_config = lambda commands: "\n".join(commands) + "\n% Invalid command"
    history = CommandHistory()
    with pytest.raises(CommandError):
        history.execute(SetHostname(conn.driver, "error-router"), conn)
    assert history.items == []


def test_vyos_config_exits_config_mode_and_read_timeout_maps(monkeypatch):
    import netmiko
    backend = mock.Mock()
    monkeypatch.setattr(netmiko, "ConnectHandler", lambda **kw: backend)
    conn = SSHConnection("h", 22, "u", "p", "vyos")
    conn.send_config(["set system host-name R2", "commit"])
    backend.send_config_set.assert_called_once_with(["set system host-name R2", "commit"], exit_config_mode=True)
    backend.send_command.side_effect = netmiko.ReadTimeout("slow")
    with pytest.raises(ConnectionError_) as exc:
        conn.send_command("show interfaces")
    assert exc.value.kind == "timeout"


def test_cisco_dhcp_and_secondary_do_not_break_primary_capture():
    driver = DriverFactory.create("cisco_ios")
    conn = mock.Mock()
    conn.send_command.return_value = "interface Gi0/0\n ip address dhcp\n!\ninterface Gi0/1\n ip address 10.0.0.1 255.255.255.0\n ip address 192.168.1.1 255.255.255.0 secondary\n!"
    interfaces = driver.get_interfaces(conn)
    assert interfaces[0]["ip"] == ""
    assert interfaces[1]["ip"] == "10.0.0.1/24"


def test_ping_localized_decimal_loss_and_warning_boundary():
    import subprocess
    text = "3 packets transmitted, 2 received, 33,3333% packet loss\nrtt min/avg/max/mdev = 1.0/2.0/3.0/0.1 ms"
    assert parse_ping_output(text) == (2.0, 33.3333)
    sensor = PingSensor(1, 1, "ping", "localhost", down_after=1)
    for loss, expected in [(20, Status.UP), (20.1, Status.WARNING), (100, Status.DOWN)]:
        out = text.replace("33,3333", str(loss)).encode()
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, out)):
            assert sensor.run().status == expected


def test_tc10_http_500_down_after_three_failures():
    import urllib.error
    sensor = HttpSensor(1, 1, "HTTP", "http://localhost")
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(sensor.target, 500, "down", {}, None)):
        assert sensor.run().status == Status.UNKNOWN
        assert sensor.run().status == Status.UNKNOWN
        assert sensor.run().status == Status.DOWN


def test_singleton_construction_waits_for_initialization():
    MonitorScheduler.reset_instance()
    entered, release = threading.Event(), threading.Event()
    original = threading.Event
    first = [True]

    def blocked_event():
        if first[0]:
            first[0] = False
            entered.set()
            assert release.wait(3)
        return original()

    try:
        with ThreadPoolExecutor(2) as pool:
            # Replace scheduler's module reference, not global threading.Event used by executor.
            fake_threading = mock.Mock(wraps=threading)
            fake_threading.Event = blocked_event
            with mock.patch("netmon.domain.scheduler.threading", fake_threading):
                a = pool.submit(MonitorScheduler)
                assert entered.wait(3)
                b = pool.submit(MonitorScheduler)
                try:
                    assert not b.done()
                finally:
                    release.set()
                assert a.result() is b.result()
                assert b.result().stats()["sensor_count"] == 0
    finally:
        release.set()
        MonitorScheduler.reset_instance()


def test_scheduler_cancelled_and_removed_queued_jobs_release_inflight():
    MonitorScheduler.reset_instance()
    scheduler = MonitorScheduler(max_workers=1, clock=lambda: 0)
    entered, release = threading.Event(), threading.Event()
    first, second = Probe(), Probe()
    second.id = 2

    def block():
        entered.set()
        assert release.wait(3)
        return CheckResult(Status.UP)

    first.check = block
    second.check = mock.Mock(return_value=CheckResult(Status.UP))
    try:
        scheduler.add_sensor(first)
        scheduler.add_sensor(second)
        scheduler.start()
        assert entered.wait(3)
        scheduler.remove_sensor(2)
        release.set()
        scheduler.stop()
        second.check.assert_not_called()
        assert scheduler.stats()["in_flight"] == 0
    finally:
        release.set()
        MonitorScheduler.reset_instance()


def test_scheduler_cancel_pending_jobs_does_not_leak_inflight():
    MonitorScheduler.reset_instance()
    scheduler = MonitorScheduler(max_workers=1, clock=lambda: 0)
    entered, release = threading.Event(), threading.Event()
    first, second = Probe(), Probe()
    second.id = 2

    def block():
        entered.set()
        assert release.wait(3)
        return CheckResult(Status.UP)

    first.check = block
    try:
        scheduler.add_sensor(first)
        scheduler.add_sensor(second)
        scheduler.start()
        assert entered.wait(3)
        pool = scheduler._pool
        scheduler.stop(wait=False)
        release.set()
        pool.shutdown(wait=True)
        assert scheduler.stats()["in_flight"] == 0
    finally:
        release.set()
        MonitorScheduler.reset_instance()


def test_warning_breaks_down_streak_and_observer_failure_isolated():
    sensor = Probe()
    bad, good = mock.Mock(), mock.Mock()
    bad.on_status_changed.side_effect = RuntimeError("broken")
    bad.on_result.side_effect = RuntimeError("broken")
    sensor.attach(bad)
    sensor.attach(good)
    sensor.next = Status.DOWN
    sensor.run()
    sensor.run()
    sensor.next = Status.WARNING
    assert sensor.run().status == Status.WARNING
    assert sensor.consecutive_failures == 0
    sensor.next = Status.DOWN
    assert sensor.run().status == Status.WARNING
    assert sensor.consecutive_failures == 1
    assert good.on_status_changed.call_count == 1
    assert good.on_result.call_count == 4


def test_run_pause_concurrent_results_are_ordered_and_paused_checks_skipped():
    sensor, entered, release, events = Probe(), threading.Event(), threading.Event(), []

    def check():
        entered.set()
        assert release.wait(3)
        return CheckResult(Status.UP)

    sensor.check = check
    sensor.attach(mock.Mock(on_result=lambda s, r: events.append(r.status),
                            on_status_changed=lambda s, old, r: events.append(r.status)))
    with ThreadPoolExecutor(2) as pool:
        running = pool.submit(sensor.run)
        assert entered.wait(3)
        paused = pool.submit(sensor.pause)
        release.set()
        running.result()
        paused.result()
    assert events == [Status.UP, Status.UP, Status.PAUSED]
    sensor.check = mock.Mock()
    assert sensor.run().status == Status.PAUSED
    sensor.check.assert_not_called()


def test_concurrent_scheduler_start_creates_one_pool():
    MonitorScheduler.reset_instance()
    scheduler = MonitorScheduler()
    original = ThreadPoolExecutor
    try:
        with mock.patch("netmon.domain.scheduler.ThreadPoolExecutor", wraps=original) as pools:
            with original(8) as callers:
                list(callers.map(lambda _: scheduler.start(), range(16)))
            assert pools.call_count == 1
            scheduler.stop()
    finally:
        MonitorScheduler.reset_instance()


def test_acknowledge_is_serialized_with_resolution():
    sensor, manager = Probe(down_after=1), AlertManager()
    sensor.attach(manager)
    sensor.next = Status.DOWN
    sensor.run()
    alert = manager.open_alerts()[0]
    entered, release = threading.Event(), threading.Event()
    original = alert.ack

    def ack(user, note):
        entered.set()
        assert release.wait(3)
        original(user, note)

    alert.ack = ack
    with ThreadPoolExecutor(2) as pool:
        acknowledging = pool.submit(manager.acknowledge, alert.id, "admin")
        assert entered.wait(3)
        sensor.next = Status.UP
        recovery = pool.submit(sensor.run)
        release.set()
        acknowledging.result()
        recovery.result()
    assert alert.state == AlertState.RESOLVED
    assert manager.open_alerts() == []


@pytest.mark.parametrize("driver", ["vyos", "mikrotik"])
def test_multiple_interface_addresses_rejected_before_writes(driver):
    from netmon.domain.remote import SetInterfaceIP
    conn = FakeConnection(driver=driver)
    original_show = conn.send_command

    def show(command):
        text = original_show(command)
        if command == "show configuration commands":
            return text + "\nset interfaces ethernet eth1 address '172.16.0.1/24'"
        if command == "/ip address print terse":
            return text + "\n 3 address=172.16.0.1/24 interface=eth1"
        return text

    conn.send_command = show
    conn.send_config = mock.Mock(wraps=conn.send_config)
    history = CommandHistory()
    with pytest.raises(ValueError, match="multiple addresses"):
        history.execute(SetInterfaceIP(conn.driver, "eth1", "192.0.2.1/24"), conn)
    conn.send_config.assert_not_called()
    assert history.items == []
    assert conn.state["interfaces"]["eth1"]["ip"] == "192.168.1.1/24"


@pytest.mark.parametrize("driver", ["vyos", "mikrotik"])
def test_unsupported_telnet_capability_fails_before_connect(driver, monkeypatch):
    import netmiko
    from netmon.domain.remote import TelnetConnection
    connect = mock.Mock()
    monkeypatch.setattr(netmiko, "ConnectHandler", connect)
    conn = TelnetConnection("h", 23, "u", "p", driver)
    with pytest.raises(ConnectionError_, match="Telnet unsupported") as exc:
        conn.connect()
    assert exc.value.kind == "other"
    connect.assert_not_called()


def test_notifier_failure_never_exposes_exception_secrets(caplog):
    from netmon.domain.alerts import Alert, AlertLevel, TelegramNotifier, WebNotifier
    secret = "REVIEW_SECRET_TOKEN"
    notifier = TelegramNotifier(secret, "42")
    sent = []
    manager = AlertManager(notifiers=[notifier, WebNotifier(lambda *args: sent.append(args))])
    with mock.patch("urllib.request.urlopen", side_effect=RuntimeError(
            f"https://api.telegram.org/bot{secret}/sendMessage password=SMTP_SECRET")):
        result = manager.dispatch(Alert(1, 1, AlertLevel.CRITICAL, "down", Status.DOWN))
    assert result == {"telegram": "error: notification failed", "web": "ok"}
    assert len(sent) == 1
    assert secret not in caplog.text and "SMTP_SECRET" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
