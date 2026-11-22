/* NetMon realtime: Socket.IO namespace /ws/status. Exposes window.NM.rt = { socket, counts }.
   Every event is re-dispatched on document as CustomEvent 'netmon:<event>' (detail = payload). */
(function () {
  'use strict';
  var NM = window.NM = window.NM || {};
  var rt = NM.rt = { socket: null, counts: null };

  function $all(sel) { return document.querySelectorAll(sel); }
  function fire(name, detail) { document.dispatchEvent(new CustomEvent('netmon:' + name, { detail: detail })); }
  function touch() {
    var el = document.getElementById('rt-last-update');
    if (el) el.textContent = NM.fmt.time(new Date());
  }

  function setConn(ok) {
    var el = document.getElementById('rt-status');
    if (!el) return;
    el.classList.toggle('connected', ok);
    el.querySelector('.rt-label').textContent = ok ? 'Đã kết nối realtime' : 'Mất kết nối – đang thử lại…';
  }

  /* header squares: #hdr-count-down|warning|up|paused (hidden when 0); dashboard: [data-count-status="DOWN|...|total"] */
  function updateCounts(c) {
    if (!c) return;
    rt.counts = c;
    ['DOWN', 'WARNING', 'UP', 'PAUSED'].forEach(function (k) {
      var a = document.getElementById('hdr-count-' + k.toLowerCase());
      var n = c[k] || 0;
      if (a) { a.hidden = !n; a.querySelector('[data-count]').textContent = n; }
    });
    $all('[data-count-status]').forEach(function (el) {
      var k = el.getAttribute('data-count-status'), n = k === 'total' ? c.total : (c[k] || 0);
      var numEl = el.querySelector('[data-count]') || el;
      if (String(numEl.textContent).trim() === String(n || 0)) return;
      numEl.textContent = n || 0;
      if (k !== 'total') {
        if (n) NM.setStatus(el, k); else {
          ['st-up', 'st-warning', 'st-down', 'st-paused'].forEach(function (x) { el.classList.remove(x); });
        }
      }
    });
  }

  function updateAlertCount(n) {
    var el = document.getElementById('menu-alert-count');
    if (!el || n == null) return;
    el.textContent = '(' + n + ')';
    el.classList.toggle('st-text-down', n > 0);
  }

  /* Status indicators carry the id themselves: .nm-tile/.nm-dot/.nm-badge/[data-status-el] with data-*-id.
     Containers (rows) with the same data-*-id are left alone, so nested groups never clash. */
  var IND = '.nm-tile,.nm-dot,.nm-badge,[data-status-el]';
  function swap(attr, id, status) {
    $all('[' + attr + '="' + id + '"]').forEach(function (el) {
      if (!el.matches(IND)) return;
      NM.setStatus(el, status);
      if (el.classList.contains('nm-badge')) el.textContent = String(status).toUpperCase();
    });
  }

  function onStatusChanged(d) {
    var st = String(d['new'] || 'UNKNOWN').toUpperCase(), old = String(d.old || '').toUpperCase();
    swap('data-sensor-id', d.sensor_id, st);
    $all('[data-sensor-id="' + d.sensor_id + '"]').forEach(function (el) {
      if (d.value !== undefined) setValue(el, d.value, el.getAttribute('data-unit'), st);
      if (d.message != null && el.classList.contains('nm-tile')) el.title = st + '\n' + d.message;
      el.querySelectorAll('[data-field="message"]').forEach(function (m) { m.textContent = d.message || NM.fmt.EMPTY; });
    });
    if (d.device_id != null && d.device_status) swap('data-device-id', d.device_id, d.device_status);
    var gs = d.group_statuses || {};
    Object.keys(gs).forEach(function (gid) { swap('data-group-id', gid, gs[gid]); });
    updateCounts(d.counts);
    if (st === 'DOWN' && old !== 'DOWN') NM.toast('DOWN: ' + label(d) + (d.message ? ' – ' + d.message : ''), 'DOWN');
    else if (st === 'UP' && (old === 'DOWN' || old === 'WARNING')) NM.toast('Đã khôi phục UP: ' + label(d), 'UP');
  }
  function label(d) {
    var tile = document.querySelector('.nm-tile[data-sensor-id="' + d.sensor_id + '"] .nm-tile-name');
    return d.sensor_name || (d.device_name ? d.device_name + ' · ' : '') + (tile ? tile.textContent.trim() : 'Sensor #' + d.sensor_id);
  }

  function setValue(el, value, unit, status) {
    var txt = value == null ? (status && status !== 'UP' ? status : NM.fmt.EMPTY) : NM.fmt.value(value, unit);
    var nodes = el.matches('[data-field="value"]') ? [el] : el.querySelectorAll('[data-field="value"]');
    nodes.forEach(function (n) { n.textContent = txt; });
  }

  function onResult(d) {
    $all('[data-sensor-id="' + d.sensor_id + '"]').forEach(function (el) {
      if (d.unit) el.setAttribute('data-unit', d.unit);
      setValue(el, d.value, d.unit || el.getAttribute('data-unit'), el.getAttribute('data-status'));
      el.querySelectorAll('[data-field="last_check"]').forEach(function (t) {
        t.setAttribute('datetime', d.ts); NM.renderFormats(t.parentNode);
      });
      el.querySelectorAll('[data-field="message"]').forEach(function (m) { m.textContent = d.message || NM.fmt.EMPTY; });
    });
  }

  function onAlert(d) { updateAlertCount(d && d.open_count); }

  function connect() {
    if (typeof io === 'undefined') { setConn(false); return; }
    var s = rt.socket = io('/ws/status', {
      transports: ['websocket', 'polling'],
      reconnection: true, reconnectionDelay: 5000, reconnectionDelayMax: 5000
    });
    s.on('connect', function () { setConn(true); touch(); fire('connect', {}); });
    s.on('disconnect', function () { setConn(false); fire('disconnect', {}); });
    s.on('connect_error', function () { setConn(false); });
    var handlers = {
      sensor_status_changed: onStatusChanged,
      sensor_result: onResult,
      alert_opened: onAlert,
      alert_updated: onAlert
    };
    Object.keys(handlers).forEach(function (ev) {
      s.on(ev, function (data) {
        try { handlers[ev](data || {}); } catch (e) { if (window.console) console.error(e); }
        touch();
        fire(ev, data || {});
      });
    });
  }

  NM.rt.updateCounts = updateCounts;
  NM.rt.updateAlertCount = updateAlertCount;
  document.addEventListener('DOMContentLoaded', connect);
})();
