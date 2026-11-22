/* NetMon tree. Exposes window.NM.tree = { init(root), expand(groupId), collapse(groupId) }.
   Markup:
   <ul class="nm-tree" data-tree="devices">            (data-tree = localStorage key suffix)
     <li class="nm-tree-group" data-tree-node="GROUP_ID" [data-default-open] [data-draggable="group" data-id=..]>
       <div class="nm-tree-row" data-drop-group="GROUP_ID">
         <button class="nm-tree-toggle" data-tree-toggle>▾</button> <span class="nm-dot st-..." data-group-id=..></span> ...
       </div>
       <ul class="nm-tree">... children ...</ul>
     </li>
   Drag: [data-draggable="device|group"][data-id] onto [data-drop-group] fires
   document 'netmon:move' detail {kind, id, target_group_id}. Page decides (confirm + API). */
(function () {
  'use strict';
  var NM = window.NM = window.NM || {};
  var PREFIX = 'nm-tree:';

  function load(key) {
    try { return JSON.parse(localStorage.getItem(PREFIX + key) || '{}') || {}; } catch (e) { return {}; }
  }
  function save(key, state) {
    try { localStorage.setItem(PREFIX + key, JSON.stringify(state)); } catch (e) { /* storage unavailable */ }
  }

  function setOpen(li, open) {
    li.classList.toggle('nm-collapsed', !open);
    var t = li.querySelector(':scope > .nm-tree-row [data-tree-toggle]');
    if (t) { t.textContent = open ? '▾' : '▸'; t.setAttribute('aria-expanded', open ? 'true' : 'false');
      t.setAttribute('aria-label', open ? 'Thu gọn' : 'Mở rộng'); }
  }

  function initTree(tree) {
    var key = tree.getAttribute('data-tree') || 'default';
    var state = load(key);
    tree.querySelectorAll('[data-tree-node]').forEach(function (li) {
      var id = li.getAttribute('data-tree-node');
      setOpen(li, id in state ? !!state[id] : li.hasAttribute('data-default-open'));
    });
    tree.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-tree-toggle]');
      if (!btn || !tree.contains(btn)) return;
      var li = btn.closest('[data-tree-node]');
      var open = li.classList.contains('nm-collapsed');
      setOpen(li, open);
      state[li.getAttribute('data-tree-node')] = open;
      save(key, state);
    });
  }

  function initDnd(root) {
    var drag = null;
    root.addEventListener('dragstart', function (e) {
      var el = e.target.closest && e.target.closest('[data-draggable]');
      if (!el) return;
      drag = { kind: el.getAttribute('data-draggable'), id: el.getAttribute('data-id'), el: el };
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', drag.kind + ':' + drag.id); } catch (x) { /* IE */ }
      e.stopPropagation();
    });
    root.addEventListener('dragend', function () { drag = null; clear(); });
    function clear() { root.querySelectorAll('.nm-drop-over').forEach(function (n) { n.classList.remove('nm-drop-over'); }); }
    function target(e) {
      var t = e.target.closest && e.target.closest('[data-drop-group]');
      if (!t || !drag) return null;
      if (drag.el.contains(t)) return null; // cannot drop onto self / own subtree
      return t;
    }
    root.addEventListener('dragover', function (e) {
      var t = target(e); if (!t) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'move';
      if (!t.classList.contains('nm-drop-over')) { clear(); t.classList.add('nm-drop-over'); }
    });
    root.addEventListener('dragleave', function (e) {
      var t = e.target.closest && e.target.closest('[data-drop-group]');
      if (t && !t.contains(e.relatedTarget)) t.classList.remove('nm-drop-over');
    });
    root.addEventListener('drop', function (e) {
      var t = target(e); if (!t) return;
      e.preventDefault(); clear();
      document.dispatchEvent(new CustomEvent('netmon:move', { detail: {
        kind: drag.kind, id: drag.id, target_group_id: t.getAttribute('data-drop-group'),
        source: drag.el, target: t } }));
      drag = null;
    });
  }

  function init(root) {
    root = root || document;
    root.querySelectorAll('[data-tree]').forEach(function (t) { if (!t._nmInit) { t._nmInit = true; initTree(t); } });
    root.querySelectorAll('[data-draggable]').forEach(function (el) { el.setAttribute('draggable', 'true'); });
  }
  function byId(id) { return document.querySelector('[data-tree-node="' + id + '"]'); }

  NM.tree = {
    init: init,
    expand: function (id) { var li = byId(id); if (li) setOpen(li, true); },
    collapse: function (id) { var li = byId(id); if (li) setOpen(li, false); }
  };
  document.addEventListener('DOMContentLoaded', function () { init(document); initDnd(document); });
})();
