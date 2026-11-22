"""Browser acceptance run (TC-01..TC-16) against a live NetMon server on a throwaway DB.

Needs: pip install playwright && python -m playwright install chromium
Start server with ADMIN_USERNAME=smokeadmin ADMIN_PASSWORD=Sm0ke-Test-Pass-91 and a fresh DATABASE_URL, then:
    python -X utf8 scripts/acceptance.py http://127.0.0.1:5000 <screenshot_dir> 47811
Browser drives the UI; same-origin fetch (same session + CSRF) covers API checks. A local TCP listener
stands in for a lab device we can kill and revive (TC-07..TC-11)."""
import json, socket, sys, threading, time
from playwright.sync_api import sync_playwright

BASE, OUT, PORT = sys.argv[1], sys.argv[2], int(sys.argv[3])
ADMIN = ("smokeadmin", "Sm0ke-Test-Pass-91")
results, errors = [], []


class Listener:  # fake "router" service: TCP port we can open/close
    def __init__(self, port):
        self.port, self.sock = port, None
    def up(self):
        self.sock = socket.socket(); self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port)); self.sock.listen(16)
        threading.Thread(target=self._accept, daemon=True).start()
    def _accept(self):
        s = self.sock
        while True:
            try: c, _ = s.accept(); c.close()
            except OSError: return
    def down(self):
        self.sock.close(); self.sock = None


def check(tc, name, ok, detail=""):
    results.append({"tc": tc, "name": name, "ok": bool(ok), "detail": str(detail)[:300]})


def shot(page, name):
    page.screenshot(path=f"{OUT}/{name}.png", full_page=True)


JS_API = """async ([method, url, body]) => {
  const s = await (await fetch('/api/auth/session')).json();
  const opt = {method, headers: {'X-CSRFToken': s.csrf_token}};
  if (body !== null) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  const text = await r.text(); let data = null; try { data = JSON.parse(text); } catch (e) { data = text.slice(0, 200); }
  return {status: r.status, data, type: r.headers.get('content-type')};
}"""


def api(page, method, url, body=None):
    return page.evaluate(JS_API, [method, url, body])


def login(page, user, pw):
    page.goto(f"{BASE}/login")
    page.locator("#username").fill(user); page.locator("#password").fill(pw)
    page.get_by_role("button", name="Đăng nhập").click()


def wait_status(page, sensor_id, want, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = api(page, "GET", f"/api/sensors/{sensor_id}")
        st = (r["data"].get("sensor") or r["data"]).get("status") if isinstance(r["data"], dict) else None
        if st == want: return True
        api(page, "POST", f"/api/sensors/{sensor_id}/check", {})
        time.sleep(1)
    return False


def alerts(page, state="ALL"):
    return api(page, "GET", f"/api/alerts?state={state}")["data"]["alerts"]


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1366, "height": 900})
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"[:200]))
    dev = Listener(PORT)

    # ---------- TC-01 lockout ----------
    for _ in range(5):
        login(page, "lockme", "bad"); page.wait_for_timeout(200)
    login(page, *ADMIN); page.wait_for_url(f"{BASE}/", timeout=10000)
    r = api(page, "POST", "/api/settings/users", {"username": "lockme", "role": "operator", "password": "Lockme-Pass-123"})
    check("TC-01", "create operator", r["status"] == 201, r)
    api(page, "POST", "/api/auth/logout", {})
    for _ in range(5):
        login(page, "lockme", "wrong-password"); page.wait_for_timeout(300)
    login(page, "lockme", "Lockme-Pass-123"); page.wait_for_timeout(800)
    body = page.locator("body").inner_text()
    check("TC-01", "5 wrong passwords lock account (correct pw refused)", "/login" in page.url and ("khóa" in body.lower() or "khoá" in body.lower()), body[-200:])
    shot(page, "f01-lockout")

    login(page, *ADMIN); page.wait_for_url(f"{BASE}/", timeout=10000)

    # ---------- inventory: groups tree, TC-05 ----------
    g_a = api(page, "POST", "/api/settings/groups", {"name": "Tòa A", "parent_id": None})
    groups = api(page, "GET", "/api/groups")["data"]["groups"]
    a_id = next(g["id"] for g in groups if g["name"].endswith("Tòa A"))
    api(page, "POST", "/api/settings/groups", {"name": "Tầng 2", "parent_id": a_id})
    groups = api(page, "GET", "/api/groups")["data"]["groups"]
    t2 = next(g["id"] for g in groups if g["name"].endswith("Tầng 2"))
    cyc = api(page, "PUT", f"/api/settings/groups/{a_id}", {"name": "Tòa A", "parent_id": t2})
    check("FR-14", "group cycle rejected", cyc["status"] == 400, cyc)

    # TC-03 via API too
    bad = api(page, "POST", "/api/devices", {"name": "X", "ip": "192.168.1.300", "device_type": "pc", "group_id": t2})
    check("TC-03", "invalid IPv4 -> 400 field error", bad["status"] == 400 and "ip" in json.dumps(bad["data"]), bad)

    # router R1 = our TCP listener; fake protocol for config demo
    dev.up()
    r1 = api(page, "POST", "/api/devices", {"name": "R1", "ip": "127.0.0.1", "device_type": "router", "group_id": t2,
        "protocol": "fake", "port": 22, "username": "admin", "password": "LabPass-R1-secret", "driver": "vyos", "default_sensors": []})
    check("TC-04", "create router", r1["status"] == 201, r1)
    r1_id = r1["data"]["id"]
    for i in range(3):
        api(page, "POST", "/api/devices", {"name": f"UP{i}", "ip": f"127.0.0.{10+i}", "device_type": "pc", "group_id": t2})
    dup = api(page, "POST", "/api/devices", {"name": "UP0", "ip": "127.0.0.99", "device_type": "pc", "group_id": t2})
    check("FR-10", "duplicate name rejected", dup["status"] == 400, dup)

    srv = api(page, "POST", "/api/devices", {"name": "SRV", "ip": "127.0.0.5", "device_type": "server", "group_id": t2})
    det = api(page, "GET", f"/api/devices/{srv['data']['id']}")["data"]
    check("TC-04", "server gets Ping + HTTP sensors", sorted(s["type"] for s in det["sensors"]) == ["http", "ping"], [s["type"] for s in det["sensors"]])

    # port sensor on R1 -> our listener, down_after 3, interval 10
    ps = api(page, "POST", "/api/sensors", {"device_id": r1_id, "type": "port", "name": "Port lab", "interval": 10,
        "timeout": 1, "down_after": 3, "params": {"port": PORT}})
    check("FR-30", "add port sensor", ps["status"] == 201, ps)
    ps_id = ps["data"]["id"]
    check("FR-32", "listener open -> UP", wait_status(page, ps_id, "UP", 20))

    # ---------- TC-07: device dies ----------
    page.goto(f"{BASE}/"); page.wait_for_timeout(1500)
    dev.down()
    t0 = time.time()
    went_down = wait_status(page, ps_id, "DOWN", 40)
    check("TC-07", "sensor DOWN after 3 consecutive failures", went_down, f"{time.time()-t0:.1f}s")
    page.wait_for_timeout(2000)
    shot(page, "f02-dashboard-down")
    hdr = page.locator(".nm-summary").inner_text()
    check("TC-07", "header shows DOWN count live (no reload)", "DOWN" in hdr, hdr)
    tree = api(page, "GET", "/api/dashboard")["data"]["tree"]
    def find(nodes, name):
        for n in nodes:
            if n["name"] == name: return n
            f = find(n["children"], name)
            if f: return f
    check("TC-05", "group with 1 DOWN + 3 UP shows DOWN", find(tree, "Tầng 2")["status"] == "DOWN" and find(tree, "Tòa A")["status"] == "DOWN", find(tree, "Tầng 2")["status"])
    open_alerts = [a for a in alerts(page, "OPEN") if a["sensor_id"] == ps_id]
    check("TC-07", "exactly one OPEN alert", len(open_alerts) == 1, open_alerts)

    # ---------- TC-08: stays down, no new alerts ----------
    for _ in range(5):
        api(page, "POST", f"/api/sensors/{ps_id}/check", {}); time.sleep(0.3)
    check("TC-08", "5 more DOWN checks -> no new alert", len([a for a in alerts(page) if a["sensor_id"] == ps_id]) == 1)

    # ---------- UC-04 ack via UI ----------
    page.goto(f"{BASE}/alerts"); page.wait_for_timeout(1500)
    shot(page, "f03-alerts-open")
    ack = api(page, "POST", f"/api/alerts/{open_alerts[0]['id']}/ack", {"note": "đang kiểm tra"})
    a = next(x for x in alerts(page) if x["id"] == open_alerts[0]["id"])
    check("UC-04", "acknowledge with note", ack["status"] == 200 and a["state"] == "ACKNOWLEDGED" and a.get("note") == "đang kiểm tra", a)

    # ---------- TC-09: revive ----------
    dev.up()
    check("TC-09", "sensor back UP", wait_status(page, ps_id, "UP", 30))
    a = next(x for x in alerts(page) if x["id"] == open_alerts[0]["id"])
    check("TC-09", "alert auto RESOLVED", a["state"] == "RESOLVED", a["state"])
    ack2 = api(page, "POST", f"/api/alerts/{a['id']}/ack", {"note": "x"})
    check("UC-04", "ack RESOLVED alert refused", ack2["status"] >= 400, ack2["status"])

    # ---------- TC-10: HTTP 500 ----------
    import http.server
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(500); self.end_headers()
        def log_message(self, *a): pass
    hs = http.server.HTTPServer(("127.0.0.1", PORT + 1), H); threading.Thread(target=hs.serve_forever, daemon=True).start()
    hsens = api(page, "POST", "/api/sensors", {"device_id": r1_id, "type": "http", "name": "HTTP500", "interval": 10, "timeout": 2,
        "down_after": 1, "params": {"url": f"http://127.0.0.1:{PORT+1}/"}})
    check("TC-10", "HTTP 500 -> DOWN", hsens["status"] == 201 and wait_status(page, hsens["data"]["id"], "DOWN", 20), hsens)
    hs.shutdown()

    # ---------- TC-11: pause group, kill device ----------
    alerts_before = len(alerts(page))
    pg = api(page, "POST", f"/api/groups/{t2}/pause", {})
    dev.down()
    for _ in range(4):
        api(page, "POST", f"/api/sensors/{ps_id}/check", {}); time.sleep(0.3)
    st = api(page, "GET", f"/api/sensors/{ps_id}")["data"]
    st = (st.get("sensor") or st)["status"]
    check("TC-11", "paused group: sensor PAUSED, no new alert", pg["status"] == 200 and st == "PAUSED" and len(alerts(page)) == alerts_before, (pg["status"], st))
    api(page, "POST", f"/api/groups/{t2}/resume", {}); dev.up()

    # ---------- config: TC-12, TC-13, TC-14, TC-16 ----------
    base = f"/api/devices/{r1_id}/config"
    conn = api(page, "POST", f"{base}/connection", {})
    check("FR-61", "connection test ok (fake)", conn["status"] == 200 and conn["data"].get("ok"), conn)
    b1 = api(page, "POST", f"{base}/backup", {})
    prev = api(page, "POST", f"{base}/preview", {"command_type": "set_hostname", "params": {"name": "CORE1"}})
    check("FR-64", "preview lists commands", prev["status"] == 200 and prev["data"]["commands"], prev)
    ex = api(page, "POST", f"{base}/execute", {"command_type": "set_hostname", "params": {"name": "CORE1"}})
    b2 = api(page, "POST", f"{base}/backup", {})
    d = api(page, "GET", f"{base}/diff?a={b1['data']['backup']['id']}&b={b2['data']['backup']['id']}")
    changed = [row for row in d["data"].get("diff", d["data"]) if isinstance(row, dict) and row.get("kind") != "same"] if d["status"] == 200 else d
    check("TC-12", "diff differs only in hostname line", ex["status"] == 200 and isinstance(changed, list) and changed and all("CORE1" in (r.get("left") or "") + (r.get("right") or "") or "R1" in (r.get("left") or "") + (r.get("right") or "") for r in changed), changed)

    off = api(page, "POST", f"{base}/execute", {"command_type": "toggle_interface", "params": {"iface": "eth1", "enable": False}})
    ifs = {i["name"]: i["status"] for i in api(page, "GET", f"{base}/interfaces")["data"]["interfaces"]}
    hist = api(page, "GET", f"/api/devices/{r1_id}")["data"]["config_history"]
    old_undo = api(page, "POST", f"{base}/undo", {"command_id": hist[-1]["id"] if hist[0]["id"] == max(h["id"] for h in hist) else hist[0]["id"]})
    newest = max(hist, key=lambda h: h["id"])
    oldest = min(hist, key=lambda h: h["id"])
    out_of_order = api(page, "POST", f"{base}/undo", {"command_id": oldest["id"]})
    un = api(page, "POST", f"{base}/undo", {"command_id": newest["id"]})
    ifs2 = {i["name"]: i["status"] for i in api(page, "GET", f"{base}/interfaces")["data"]["interfaces"]}
    hist2 = api(page, "GET", f"/api/devices/{r1_id}")["data"]["config_history"]
    check("TC-13", "eth1 down then undo -> up, marked undone", off["status"] == 200 and ifs.get("eth1") == "down" and un["status"] == 200 and ifs2.get("eth1") == "up" and next(h for h in hist2 if h["id"] == newest["id"])["undone"], (ifs, ifs2))
    check("UC-07", "undo older change before newer -> refused", out_of_order["status"] >= 400, out_of_order["status"])
    syn = api(page, "POST", f"{base}/execute", {"command_type": "toggle_interface", "params": {"iface": "eth9", "enable": False}})
    check("UC-06", "bad interface -> error, not saved", syn["status"] >= 400 and len(api(page, "GET", f"/api/devices/{r1_id}")["data"]["config_history"]) == len(hist2), syn)

    # UI config tab screenshot
    page.goto(f"{BASE}/devices/{r1_id}"); page.wait_for_timeout(1200)
    page.get_by_role("tab", name="Cấu hình").or_(page.get_by_text("Cấu hình", exact=True)).first.click(); page.wait_for_timeout(2000)
    shot(page, "f04-config-tab")

    # TC-14: wrong password on real SSH path (port with nothing listening)
    api(page, "PUT", f"{base}/credentials", {"protocol": "ssh", "port": PORT + 2, "username": "admin", "password": "wrong", "driver": "vyos"})
    t = time.time(); c2 = api(page, "POST", f"{base}/connection", {}); dt = time.time() - t
    check("TC-14", "failed connection reported clearly, UI not hung", c2["status"] in (200, 400, 502) and c2["data"].get("ok") is False and c2["data"].get("message") and dt < 30, (c2, f"{dt:.1f}s"))

    # ---------- discovery TC-06 (loopback) + FR-18 ----------
    big = api(page, "POST", "/api/discovery", {"cidr": "10.0.0.0/21", "ports": "22,80"})
    check("FR-18", "CIDR larger than /22 rejected", big["status"] == 400, big)
    pub = api(page, "POST", "/api/discovery", {"cidr": "8.8.8.0/24", "ports": "22"})
    check("FR-18", "public range outside ALLOWED_NETWORKS rejected", pub["status"] == 400, pub)
    job = api(page, "POST", "/api/discovery", {"cidr": "127.0.0.0/29", "ports": f"22,{PORT}"})
    jid = job["data"].get("id") or job["data"].get("job_id")
    st = {}
    for _ in range(60):
        st = api(page, "GET", f"/api/discovery/{jid}")["data"]
        if st.get("status") in ("completed", "stopped", "failed"): break
        time.sleep(1)
    found = {r["ip"]: r for r in st.get("results", [])}
    check("TC-06", "scan finds live hosts and marks existing ones", st.get("status") == "completed" and found.get("127.0.0.1", {}).get("exists") is True, {k: v.get("exists") for k, v in found.items()})
    page.goto(f"{BASE}/discovery"); page.wait_for_timeout(1000); shot(page, "f05-discovery")

    # ---------- reports + export ----------
    rep = api(page, "GET", "/api/reports?range=7d")
    check("F-14", "report rows with uptime", rep["status"] == 200 and rep["data"]["rows"], rep["data"].get("summary") if isinstance(rep["data"], dict) else rep)
    csv_r = api(page, "GET", "/api/reports/export.csv?range=7d")
    check("F-15", "CSV export", csv_r["status"] == 200 and "csv" in (csv_r["type"] or ""), csv_r["type"])
    pdf = page.evaluate("async () => { const r = await fetch('/api/reports/export.pdf?range=7d'); const b = new Uint8Array(await r.arrayBuffer()); return [r.status, r.headers.get('content-type'), String.fromCharCode(...b.slice(0,5)), b.length]; }")
    check("F-15", "PDF export", pdf[0] == 200 and pdf[2] == "%PDF-", pdf)
    dcsv = api(page, "GET", "/api/devices/export.csv")
    check("F-05", "device CSV export", dcsv["status"] == 200, dcsv["type"])
    page.goto(f"{BASE}/reports"); page.wait_for_timeout(1500); shot(page, "f06-reports")

    # ---------- notifier channels: secrets write-only ----------
    api(page, "PUT", "/api/alerts/channels/telegram", {"enabled": True, "token": "123:TOKEN-SECRET-XYZ", "chat_id": "42"})
    ch = api(page, "GET", "/api/alerts/channels")
    check("NFR-04", "telegram token never returned", "TOKEN-SECRET-XYZ" not in json.dumps(ch["data"]), "")
    tst = api(page, "POST", "/api/alerts/channels/telegram/test", {})
    check("FR-43", "send test reports failure without secret", "TOKEN-SECRET-XYZ" not in json.dumps(tst["data"]), tst)

    # ---------- audit + settings ----------
    logs = api(page, "GET", "/api/logs")["data"]["logs"]
    acts = {l["action"] for l in logs}
    check("FR-70", "audit has login/create/config entries", any("login" in a for a in acts) and len(logs) > 5, sorted(acts)[:15])
    sset = api(page, "PUT", "/api/settings/monitoring", {"default_interval": 45, "down_after": 3, "history_days": 30, "backup_time": "02:00"})
    check("FR-71", "save monitoring settings", sset["status"] == 200, sset)
    me = api(page, "GET", "/api/auth/session")["data"]["user"]["id"]
    demote = api(page, "PUT", f"/api/settings/users/{me}", {"role": "viewer"})
    check("FR-71", "cannot demote last/self admin", demote["status"] == 400, demote)
    page.goto(f"{BASE}/settings"); page.wait_for_timeout(1500); shot(page, "f07-settings")

    # ---------- TC-02 viewer ----------
    api(page, "POST", "/api/settings/users", {"username": "viewer1", "role": "viewer", "password": "Viewer-Pass-123"})
    vctx = browser.new_context(); vp = vctx.new_page()
    login(vp, "viewer1", "Viewer-Pass-123"); vp.wait_for_url(f"{BASE}/", timeout=10000)
    dl = api(vp, "DELETE", f"/api/devices/{r1_id}")
    rc = api(vp, "GET", f"{base}/running")
    dd = api(vp, "GET", f"/api/devices/{r1_id}")["data"]
    check("TC-02", "viewer DELETE -> 403, device intact", dl["status"] == 403 and api(page, "GET", f"/api/devices/{r1_id}")["status"] == 200, dl["status"])
    check("§7", "viewer cannot read running-config/credentials", rc["status"] == 403 and "credential" not in dd["device"] and not dd.get("backups"), rc["status"])
    vctx.close()

    # ---------- password change kills other sessions ----------
    c3 = browser.new_context(); p3 = c3.new_page(); login(p3, "viewer1", "Viewer-Pass-123"); p3.wait_for_url(f"{BASE}/")
    c4 = browser.new_context(); p4 = c4.new_page(); login(p4, "viewer1", "Viewer-Pass-123"); p4.wait_for_url(f"{BASE}/")
    cp = api(p3, "POST", "/api/account/password", {"current_password": "Viewer-Pass-123", "new_password": "Viewer-Pass-456", "confirm_password": "Viewer-Pass-456"})
    check("FR-01", "password change invalidates other sessions", cp["status"] == 200 and api(p4, "GET", "/api/devices")["status"] == 401 and api(p3, "GET", "/api/devices")["status"] == 200, cp)
    c3.close(); c4.close()

    # ---------- delete keeps alert history (FR-13) ----------
    n_alerts = len([a for a in alerts(page) if a["sensor_id"] == ps_id])
    dl2 = api(page, "DELETE", f"/api/devices/{r1_id}")
    kept = [a for a in alerts(page) if a.get("sensor_name") == "Port lab"]
    check("FR-13", "delete device keeps its alerts", dl2["status"] == 200 and len(kept) >= n_alerts >= 1, (n_alerts, len(kept)))

    print(json.dumps(results, ensure_ascii=False, indent=0))
    print("PAGE_ERRORS", errors)
    browser.close()
