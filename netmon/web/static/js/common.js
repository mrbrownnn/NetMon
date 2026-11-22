/* NetMon common helpers. Exposes window.NM = { api, toast, fmt, stClass, setStatus, confirm, confirmModal, esc }. */
(function () {
  'use strict';
  var NM = window.NM = window.NM || {};
  var EMPTY = '–';

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* NM.api(url, {method, body, headers}) -> Promise<json>. Objects in body are sent as JSON.
     Rejects with Error having .status and .data (parsed body, e.g. {errors:{field:msg}}). */
  function api(url, opts) {
    opts = opts || {};
    var headers = Object.assign({ 'Accept': 'application/json', 'X-CSRFToken': csrf(),
      'X-Requested-With': 'fetch' }, opts.headers || {});
    var body = opts.body;
    if (body != null && !(body instanceof FormData) && typeof body !== 'string') {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    return fetch(url, { method: opts.method || (body != null ? 'POST' : 'GET'), headers: headers,
      body: body, credentials: 'same-origin' })
      .then(function (r) {
        var ct = r.headers.get('Content-Type') || '';
        var p = ct.indexOf('json') >= 0 ? r.json() : r.text();
        return p.then(function (data) {
          if (!r.ok) {
            var e = new Error((data && data.error) || ('Lỗi ' + r.status));
            e.status = r.status; e.data = data; throw e;
          }
          return data;
        });
      });
  }
  ['get', 'post', 'put', 'patch', 'delete'].forEach(function (m) {
    api[m] = function (url, body) { return api(url, { method: m.toUpperCase(), body: body }); };
  });

  /* ---------- status class ---------- */
  var ST = ['st-up', 'st-warning', 'st-down', 'st-down-ack', 'st-paused', 'st-unknown'];
  function stClass(status, acked) {
    var s = String(status || '').toUpperCase();
    if (s === 'DOWN' && acked) return 'st-down-ack';
    if (s === 'CRITICAL') return 'st-down';
    if (s === 'INFO') return 'st-paused';
    return ['UP', 'WARNING', 'DOWN', 'PAUSED'].indexOf(s) >= 0 ? 'st-' + s.toLowerCase() : 'st-unknown';
  }
  /* Swap st-* class on el; flash border once if changed. Returns true if changed. */
  function setStatus(el, status, acked) {
    var cls = stClass(status, acked);
    if (el.classList.contains(cls)) return false;
    ST.forEach(function (c) { el.classList.remove(c); });
    el.classList.add(cls);
    el.setAttribute('data-status', String(status || 'UNKNOWN').toUpperCase());
    el.classList.remove('nm-flash'); void el.offsetWidth; el.classList.add('nm-flash');
    setTimeout(function () { el.classList.remove('nm-flash'); }, 350);
    return true;
  }

  /* ---------- formatting (vi) ---------- */
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function toDate(v) {
    if (v == null || v === '') return null;
    var d = v instanceof Date ? v : new Date(typeof v === 'number' && v < 1e12 ? v * 1000 : v);
    return isNaN(d) ? null : d;
  }
  function num(v, digits) {
    if (v == null || v === '' || isNaN(v)) return EMPTY;
    return Number(v).toLocaleString('vi-VN', { maximumFractionDigits: digits == null ? 2 : digits });
  }
  var fmt = {
    EMPTY: EMPTY,
    num: num,
    dateTime: function (v) {
      var d = toDate(v); if (!d) return EMPTY;
      return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear() + ' ' +
        pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    },
    time: function (v) {
      var d = toDate(v); if (!d) return EMPTY;
      return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    },
    relative: function (v) {
      var d = toDate(v); if (!d) return EMPTY;
      var s = Math.round((Date.now() - d.getTime()) / 1000);
      if (s < 0) s = 0;
      if (s < 10) return 'vừa xong';
      if (s < 60) return s + ' giây trước';
      if (s < 3600) return Math.floor(s / 60) + ' phút trước';
      if (s < 86400) return Math.floor(s / 3600) + ' giờ trước';
      if (s < 86400 * 30) return Math.floor(s / 86400) + ' ngày trước';
      return fmt.dateTime(d);
    },
    pct: function (v, digits) { return v == null || v === '' || isNaN(v) ? EMPTY : num(v, digits == null ? 2 : digits) + ' %'; },
    ms: function (v) { return v == null || v === '' || isNaN(v) ? EMPTY : num(v, Number(v) < 10 ? 1 : 0) + ' ms'; },
    /* seconds -> "3 ngày 4 giờ 12 phút"; < 60s -> "45 giây" */
    duration: function (sec) {
      if (sec == null || sec === '' || isNaN(sec)) return EMPTY;
      sec = Math.max(0, Math.floor(sec));
      if (sec < 60) return sec + ' giây';
      var d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
      var out = [];
      if (d) out.push(d + ' ngày');
      if (h) out.push(h + ' giờ');
      if (m || !out.length) out.push(m + ' phút');
      return out.join(' ');
    },
    /* value with unit: ms -> fmt.ms, % -> fmt.pct, else number + unit */
    value: function (v, unit) {
      if (v == null || v === '') return EMPTY;
      if (typeof v !== 'number' && isNaN(v)) return String(v);
      if (unit === 'ms') return fmt.ms(v);
      if (unit === '%') return fmt.pct(v);
      return num(v) + (unit ? ' ' + unit : '');
    },
    bytes: function (b) {
      if (b == null || isNaN(b)) return EMPTY;
      if (b < 1024) return b + ' B';
      if (b < 1048576) return num(b / 1024, 1) + ' KB';
      return num(b / 1048576, 1) + ' MB';
    }
  };

  /* Render elements: <time data-fmt="relative|dateTime|time" datetime="ISO">, <span data-fmt="pct|ms|duration|num" data-v="..."> */
  function renderFormats(root) {
    (root || document).querySelectorAll('[data-fmt]').forEach(function (el) {
      var kind = el.getAttribute('data-fmt'), f = fmt[kind];
      if (!f) return;
      var v = el.getAttribute('datetime') || el.getAttribute('data-v');
      el.textContent = f(v === '' ? null : v, el.getAttribute('data-unit') || undefined);
      if ((kind === 'relative' || kind === 'time') && v) el.title = fmt.dateTime(v);
      el.classList.toggle('empty-val', el.textContent === EMPTY);
    });
  }

  /* ---------- toast ---------- */
  function toast(msg, status, timeout) {
    var box = document.getElementById('nm-toasts');
    if (!box) { box = document.createElement('div'); box.id = 'nm-toasts'; box.className = 'nm-toasts'; document.body.appendChild(box); }
    var t = document.createElement('div');
    t.className = 'nm-toast ' + stClass(status || 'UNKNOWN');
    t.setAttribute('role', String(status).toUpperCase() === 'DOWN' ? 'alert' : 'status');
    t.innerHTML = '<div class="nm-toast-msg"></div><button type="button" class="btn-close" aria-label="Đóng"></button>';
    t.firstChild.textContent = msg;
    t.lastChild.onclick = function () { t.remove(); };
    box.appendChild(t);
    setTimeout(function () { t.remove(); }, timeout || 5000);
    return t;
  }

  /* ---------- confirm ---------- */
  /* NM.confirmModal(id, {title, body, preview, actionLabel}) -> Promise<bool>, for modals rendered by confirm_modal macro. */
  function confirmModal(id, o) {
    o = o || {};
    var el = typeof id === 'string' ? document.getElementById(id) : id;
    if (!el || !window.bootstrap) return Promise.resolve(window.confirm(o.body || o.title || 'Xác nhận?'));
    var set = function (f, v) { var n = el.querySelector('[data-field="' + f + '"]'); if (n && v != null) n.textContent = v; return n; };
    set('title', o.title); set('body', o.body);
    var pv = el.querySelector('[data-field="preview"]');
    if (pv) {
      var lines = Array.isArray(o.preview) ? o.preview.join('\n') : o.preview;
      pv.textContent = lines || ''; pv.hidden = !lines;
    }
    var btn = el.querySelector('[data-action="confirm"]');
    if (o.actionLabel) btn.textContent = o.actionLabel;
    if (o.danger != null) { btn.classList.toggle('btn-danger', !!o.danger); btn.classList.toggle('btn-primary', !o.danger); }
    var m = bootstrap.Modal.getOrCreateInstance(el);
    return new Promise(function (resolve) {
      var ok = false;
      var onOk = function () { ok = true; m.hide(); };
      btn.addEventListener('click', onOk);
      el.addEventListener('hidden.bs.modal', function h() {
        btn.removeEventListener('click', onOk); el.removeEventListener('hidden.bs.modal', h); resolve(ok);
      });
      m.show();
    });
  }
  /* NM.confirm({title, body, preview, actionLabel, danger}) -> Promise<bool>; builds #nm-confirm on demand. */
  function confirmFn(o) {
    o = typeof o === 'string' ? { body: o } : (o || {});
    var el = document.getElementById('nm-confirm');
    if (!el) {
      el = document.createElement('div');
      el.className = 'modal'; el.id = 'nm-confirm'; el.tabIndex = -1; el.setAttribute('aria-hidden', 'true');
      el.innerHTML = '<div class="modal-dialog nm-modal-confirm"><div class="modal-content">' +
        '<div class="modal-header"><h2 class="modal-title" data-field="title"></h2>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Đóng"></button></div>' +
        '<div class="modal-body"><p class="mb-0" data-field="body"></p><pre class="nm-preview" data-field="preview" hidden></pre></div>' +
        '<div class="modal-footer"><button type="button" class="btn btn-link" data-bs-dismiss="modal">Hủy</button>' +
        '<button type="button" class="btn btn-primary" data-action="confirm"></button></div></div></div>';
      document.body.appendChild(el);
    }
    return confirmModal(el, { title: o.title || 'Xác nhận', body: o.body || '', preview: o.preview,
      actionLabel: o.actionLabel || 'Xác nhận', danger: !!o.danger });
  }

  /* Declarative: <form data-confirm="Xóa thiết bị R1?" data-confirm-danger data-confirm-label="Xóa"> or <a/button data-confirm=...> */
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f.hasAttribute || !f.hasAttribute('data-confirm') || f._nmConfirmed) return;
    e.preventDefault();
    confirmFn({ body: f.getAttribute('data-confirm'), danger: f.hasAttribute('data-confirm-danger'),
      actionLabel: f.getAttribute('data-confirm-label') }).then(function (ok) {
      if (ok) { f._nmConfirmed = true; f.submit(); }
    });
  }, true);
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-confirm]');
    if (!a) return;
    e.preventDefault();
    confirmFn({ body: a.getAttribute('data-confirm'), danger: a.hasAttribute('data-confirm-danger'),
      actionLabel: a.getAttribute('data-confirm-label') }).then(function (ok) { if (ok) location.href = a.href; });
  });

  /* ---------- quick search ---------- */
  function initQuickSearch(box) {
    var input = box.querySelector('input'), list = box.querySelector('.nm-suggest');
    var api_url = box.getAttribute('data-api') || '/api/devices', target = box.getAttribute('data-target') || '/devices';
    var timer = null, seq = 0, idx = -1;
    function hide() { list.hidden = true; idx = -1; }
    function items() { return list.querySelectorAll('a'); }
    function highlight(i) {
      var a = items(); if (!a.length) return;
      idx = (i + a.length) % a.length;
      a.forEach(function (x, j) { x.classList.toggle('active', j === idx); });
    }
    function render(rows) {
      rows = (Array.isArray(rows) ? rows : (rows && (rows.items || rows.devices)) || []).slice(0, 8);
      list.innerHTML = rows.length ? rows.map(function (d) {
        var st = String(d.status || 'UNKNOWN').toUpperCase();
        return '<a href="/devices/' + encodeURIComponent(d.id) + '"><span class="nm-badge ' + stClass(st) + '">' + esc(st) +
          '</span><span>' + esc(d.name) + '</span><span class="ip mono">' + esc(d.ip || '') + '</span></a>';
      }).join('') : '<div class="nm-suggest-empty">Không tìm thấy thiết bị</div>';
      list.hidden = false; idx = -1;
    }
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 2) { hide(); return; }
      timer = setTimeout(function () {
        var my = ++seq;
        api(api_url + '?q=' + encodeURIComponent(q) + '&limit=8')
          .then(function (rows) { if (my === seq) render(rows); })
          .catch(function () { if (my === seq) hide(); });
      }, 200);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); highlight(idx + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); highlight(idx - 1); }
      else if (e.key === 'Escape') hide();
      else if (e.key === 'Enter') {
        e.preventDefault();
        var a = items()[idx];
        location.href = a ? a.href : target + '?q=' + encodeURIComponent(input.value.trim());
      }
    });
    document.addEventListener('click', function (e) { if (!box.contains(e.target)) hide(); });
  }

  Object.assign(NM, { api: api, toast: toast, fmt: fmt, esc: esc, csrf: csrf, stClass: stClass,
    setStatus: setStatus, confirm: confirmFn, confirmModal: confirmModal, renderFormats: renderFormats });

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-quick-search]').forEach(initQuickSearch);
    renderFormats(document);
    setInterval(function () { renderFormats(document); }, 30000);
    var catMap = { success: 'UP', error: 'DOWN', danger: 'DOWN', warning: 'WARNING', info: 'PAUSED', message: 'PAUSED' };
    (window.NM_FLASH || []).forEach(function (m) { toast(m[1], catMap[m[0]] || 'PAUSED'); });
  });
})();
