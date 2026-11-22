/* NetMon tables. Exposes window.NM.table = { init(root), selected(table) }.
   Markup:
   <div class="nm-panel" data-table-wrap>          (gets .nm-bulk-active when >=1 row selected)
     <div class="nm-toolbar nm-toolbar-default">...</div>
     <div class="nm-toolbar nm-bulkbar">Đã chọn <span data-selected-count>0</span> · ...buttons...</div>
     <table class="nm-table" data-sortable>
       <th data-sort>Tên</th> <th data-sort="num">Độ trễ</th>  (td may carry data-sort-value)
       <th class="chk"><input type="checkbox" data-select-all></th> ... <td class="chk"><input type="checkbox" data-row-select value="ID"></td>
   Fires 'netmon:selection' on the wrap: detail {ids:[...]}. */
(function () {
  'use strict';
  var NM = window.NM = window.NM || {};

  function cellValue(row, i, numeric) {
    var td = row.cells[i];
    if (!td) return '';
    var v = td.hasAttribute('data-sort-value') ? td.getAttribute('data-sort-value') : td.textContent.trim();
    if (numeric) { var n = parseFloat(String(v).replace(/\./g, '').replace(',', '.')); return isNaN(n) ? -Infinity : n; }
    return v.toLocaleLowerCase('vi');
  }

  function initSort(table) {
    var heads = table.tHead ? table.tHead.rows[0].cells : [];
    Array.prototype.forEach.call(heads, function (th, i) {
      if (!th.hasAttribute('data-sort')) return;
      var ind = document.createElement('span'); ind.className = 'sort-ind'; th.appendChild(ind);
      th.setAttribute('aria-sort', 'none');
      th.addEventListener('click', function () {
        var dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
        var numeric = th.getAttribute('data-sort') === 'num';
        Array.prototype.forEach.call(heads, function (h) {
          if (h.hasAttribute('data-sort')) { h.setAttribute('aria-sort', 'none'); var s = h.querySelector('.sort-ind'); if (s) s.textContent = ''; }
        });
        th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
        ind.textContent = dir === 1 ? '▲' : '▼';
        Array.prototype.forEach.call(table.tBodies, function (tb) {
          var rows = Array.prototype.slice.call(tb.rows);
          rows.sort(function (a, b) {
            var x = cellValue(a, i, numeric), y = cellValue(b, i, numeric);
            return (x < y ? -1 : x > y ? 1 : 0) * dir;
          });
          rows.forEach(function (r) { tb.appendChild(r); });
        });
      });
    });
  }

  function selected(scope) {
    return Array.prototype.map.call(scope.querySelectorAll('[data-row-select]:checked'), function (c) { return c.value; });
  }

  function initSelect(table) {
    var wrap = table.closest('[data-table-wrap]') || table.parentNode;
    var all = table.querySelector('[data-select-all]');
    function refresh() {
      var boxes = table.querySelectorAll('[data-row-select]:not(:disabled)');
      var ids = selected(table);
      wrap.classList.toggle('nm-bulk-active', ids.length > 0);
      wrap.querySelectorAll('[data-selected-count]').forEach(function (el) { el.textContent = ids.length; });
      if (all) { all.checked = ids.length > 0 && ids.length === boxes.length; all.indeterminate = ids.length > 0 && ids.length < boxes.length; }
      wrap.dispatchEvent(new CustomEvent('netmon:selection', { bubbles: true, detail: { ids: ids } }));
    }
    table.addEventListener('change', function (e) {
      if (e.target === all) {
        table.querySelectorAll('[data-row-select]:not(:disabled)').forEach(function (c) { c.checked = all.checked; });
      }
      if (e.target === all || e.target.hasAttribute('data-row-select')) refresh();
    });
    wrap.querySelectorAll('[data-bulk-clear]').forEach(function (b) {
      b.addEventListener('click', function () {
        table.querySelectorAll('[data-row-select]').forEach(function (c) { c.checked = false; }); refresh();
      });
    });
    table._nmRefresh = refresh;
  }

  function init(root) {
    (root || document).querySelectorAll('table.nm-table').forEach(function (t) {
      if (t._nmInit) return; t._nmInit = true;
      if (t.hasAttribute('data-sortable')) initSort(t);
      if (t.querySelector('[data-row-select]') || t.querySelector('[data-select-all]')) initSelect(t);
    });
  }

  NM.table = { init: init, selected: selected };
  document.addEventListener('DOMContentLoaded', function () { init(document); });
})();
