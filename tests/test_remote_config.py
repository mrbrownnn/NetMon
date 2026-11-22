import pytest

from netmon.domain.remote import (CommandError, CommandHistory, ConnectionError_, DriverFactory, FakeConnection,
                                  SSHConnection, SetHostname, SetInterfaceIP, TelnetConnection, ToggleInterface,
                                  diff_configs, make_connection)

DRIVERS = ["vyos", "mikrotik", "cisco_ios"]


def conn(drv="vyos", **kw):
    return make_connection("fake", "10.0.0.1", 22, "admin", "pw", drv, **kw)


def test_factory():
    assert set(DRIVERS) <= set(DriverFactory.types())
    with pytest.raises(ValueError):
        DriverFactory.create("junos")
    with pytest.raises(ValueError):
        make_connection("rdp", "h", 1, "u", "p", "vyos")
    assert isinstance(make_connection("telnet", "h", 23, "u", "p", "vyos"), TelnetConnection)


@pytest.mark.parametrize("drv", DRIVERS)
def test_tc12_backup_diff_only_hostname(drv):
    with conn(drv) as c:
        d = c.driver
        before = d.get_running_config(c)
        assert d.get_hostname(c) == "R1"
        h = CommandHistory()
        h.execute(SetHostname(d, "R1-new"), c)
        after = d.get_running_config(c)
    changed = [r for r in diff_configs(before, after) if r["kind"] != "same"]
    assert [r["kind"] for r in changed] == ["del", "add"]
    assert "R1" in changed[0]["left"] and "R1-new" in changed[1]["right"]


@pytest.mark.parametrize("drv", DRIVERS)
def test_tc13_disable_eth1_then_undo(drv):
    c = conn(drv)
    d, h = c.driver, CommandHistory()
    cmd = ToggleInterface(d, "eth1", False)
    h.execute(cmd, c)
    st = {i["name"]: i for i in d.get_interfaces(c)}
    assert st["eth1"]["status"] == "down" and st["eth0"]["status"] == "up"
    assert cmd.undo_commands() == d.cmd_toggle_interface("eth1", True)
    h.undo(cmd.id, c)
    assert {i["name"]: i["status"] for i in d.get_interfaces(c)}["eth1"] == "up"
    assert cmd.undone and cmd.to_dict()["undone"] is True
    assert h.latest_undoable() is None


@pytest.mark.parametrize("drv", DRIVERS)
def test_interfaces_routes_and_set_ip(drv):
    c = conn(drv)
    d, h = c.driver, CommandHistory()
    ifs = {i["name"]: i for i in d.get_interfaces(c)}
    assert ifs["eth0"]["ip"] == "10.0.0.1/24" and ifs["eth2"]["ip"] == ""
    routes = d.get_routes(c)
    assert {"protocol": "static", "destination": "0.0.0.0/0", "gateway": "10.0.0.254",
            "interface": "eth0" if drv != "mikrotik" else ""} in routes
    assert any(r["protocol"] == "connected" and r["destination"] == "192.168.1.0/24" for r in routes)
    h.execute(SetInterfaceIP(d, "eth1", "192.168.5.1/24"), c)
    h.execute(SetInterfaceIP(d, "eth2", "172.16.0.1/16"), c)
    ip = lambda n: {i["name"]: i["ip"] for i in d.get_interfaces(c)}[n]
    assert ip("eth1") == "192.168.5.1/24" and ip("eth2") == "172.16.0.1/16"
    h.undo_last(c)
    assert ip("eth2") == ""
    h.undo_last(c)
    assert ip("eth1") == "192.168.1.1/24"
    with pytest.raises(ValueError):
        h.undo_last(c)


def test_undo_ordering():
    c = conn()
    d, h = c.driver, CommandHistory()
    h.execute(SetHostname(d, "A"), c)
    h.execute(SetHostname(d, "B"), c)
    first, second = h.items
    assert not h.can_undo(first.id) and h.can_undo(second.id)
    with pytest.raises(ValueError):
        h.undo(first.id, c)
    h.undo(second.id, c)
    assert c.state["hostname"] == "A" and h.can_undo(first.id)
    h.undo(first.id, c)
    assert c.state["hostname"] == "R1"
    assert not h.can_undo(first.id)


def test_unknown_interface_and_validation():
    c = conn()
    with pytest.raises(ValueError):
        CommandHistory().execute(SetInterfaceIP(c.driver, "eth9", "10.9.9.1/24"), c)
    with pytest.raises(ValueError):
        SetInterfaceIP(c.driver, "eth1", "300.1.1.1/24")
    with pytest.raises(ValueError):
        SetHostname(c.driver, "bad name")
    with pytest.raises(RuntimeError):
        SetHostname(c.driver, "ok").undo_commands()


@pytest.mark.parametrize("drv,marker", [("cisco_ios", "% Invalid"), ("mikrotik", "syntax error"), ("vyos", "Invalid")])
def test_uc06_device_syntax_error_not_saved(drv, marker):
    c = conn(drv)
    h = CommandHistory()

    class Bad(SetHostname):
        def preview(self):
            return ["frobnicate"]
    with pytest.raises(CommandError) as e:
        h.execute(Bad(c.driver, "X"), c)
    assert marker in e.value.output and h.items == []


def test_tc14_auth_fail():
    c = conn(fail="auth")
    with pytest.raises(ConnectionError_) as e:
        with c:
            pass
    assert e.value.kind == "auth" and "Sai thông tin đăng nhập" in str(e.value)
    assert ConnectionError_("weird").kind == "other"


def test_to_dict():
    c = conn()
    cmd = CommandHistory().push(SetHostname(c.driver, "X"))
    cmd.execute(c)
    d = cmd.to_dict()
    assert d["command_type"] == "set_hostname" and d["params"] == {"name": "X"} and d["id"] == 1
    assert d["undo_commands"] == ["set system host-name R1", "commit"] and d["executed_at"]


def test_diff_configs():
    assert diff_configs("a\nb\nc", "a\nc\nd") == [
        {"kind": "same", "left": "a", "right": "a"}, {"kind": "del", "left": "b", "right": None},
        {"kind": "same", "left": "c", "right": "c"}, {"kind": "add", "left": None, "right": "d"}]


class _FakeNetmiko:
    def __init__(self, **kw):
        self.kw = kw
        self.closed = False

    def send_command(self, cmd):
        return f"out:{cmd}"

    def send_config_set(self, cmds, **kwargs):
        return "\n".join(cmds)

    def disconnect(self):
        self.closed = True


def test_ssh_connection_wraps_netmiko(monkeypatch):
    import netmiko
    made = []
    monkeypatch.setattr(netmiko, "ConnectHandler", lambda **kw: made.append(_FakeNetmiko(**kw)) or made[-1])
    with TelnetConnection("h", 23, "u", "p", "cisco_ios") as c:
        assert c.send_command("show x") == "out:show x"
        assert c.send_config(["a", "b"]) == "a\nb"
    assert made[0].kw["device_type"] == "cisco_ios_telnet" and made[0].closed


@pytest.mark.parametrize("exc,kind", [
    ("NetmikoAuthenticationException", "auth"), ("NetmikoTimeoutException", "timeout"),
    (None, "refused"), ("ValueError", "other")])
def test_ssh_error_mapping(monkeypatch, exc, kind):
    import netmiko
    err = ConnectionRefusedError() if exc is None else (getattr(netmiko, exc, None) or ValueError)("boom")

    def boom(**kw):
        raise err
    monkeypatch.setattr(netmiko, "ConnectHandler", boom)
    with pytest.raises(ConnectionError_) as e:
        SSHConnection("h", 22, "u", "p", "cisco_ios").connect()
    assert e.value.kind == kind
