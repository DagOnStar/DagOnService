/* DAGonService dashboard: read-only monitoring through /api/v1. No build step.
 * Every server-provided string is inserted with textContent, never innerHTML. */
(function () {
  "use strict";
  var body = document.body;
  var refreshMs = Math.max(500, parseInt(body.dataset.refreshMs, 10) || 3000);
  var TOKEN_KEY = "dagonservice.token";
  var state = { selected: null, lastEvent: null, timer: null, listSig: "", detailSig: "" };

  function token() { try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } }

  function api(path) {
    var headers = { Accept: "application/json" };
    if (token()) headers.Authorization = "Bearer " + token();
    return fetch(path, { headers: headers }).then(function (r) {
      if (r.status === 401) { document.getElementById("token-form").hidden = false; throw new Error("unauthorised"); }
      return r.json().then(function (data) { if (!r.ok) throw new Error(data.message || r.statusText); return data; });
    });
  }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function svg(tag, attrs) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }
  function badge(status) { return el("span", { "class": "badge s-" + status }, status); }
  function when(iso) { if (!iso) return ""; var d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString(); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function loadHealth() {
    api("/api/v1/health").then(function (h) {
      document.getElementById("health").textContent = "Service " + h.status + " · database " + h.database;
    }).catch(function (e) { document.getElementById("health").textContent = "Service unreachable: " + e.message; });
  }

  function loadList() {
    var q = new URLSearchParams({ limit: "200" });
    var name = document.getElementById("filter").value.trim();
    var status = document.getElementById("status-filter").value;
    if (status) q.set("status", status);
    return api("/api/v1/workflows?" + q).then(function (data) {
      var tbody = document.getElementById("workflows");
      var items = data.items.filter(function (w) { return !name || w.name.toLowerCase().indexOf(name.toLowerCase()) >= 0; });
      // Re-render only on change, so keyboard focus and selection survive polling.
      var sig = JSON.stringify([items, state.selected]);
      if (sig === state.listSig) return;
      state.listSig = sig;
      clear(tbody);
      if (!items.length) { var tr = el("tr"); tr.appendChild(el("td", { colspan: "5", "class": "muted" }, "No workflows registered.")); tbody.appendChild(tr); return; }
      items.forEach(function (w) {
        var tr = el("tr", { "data-id": w.id, "aria-selected": String(w.id === state.selected) });
        var nameCell = el("td");
        var link = el("button", { type: "button", "class": "wf-link" }, w.name);
        link.addEventListener("click", function () { select(w.id); });
        nameCell.appendChild(link);
        tr.appendChild(nameCell);
        var st = el("td"); st.appendChild(badge(w.status)); tr.appendChild(st);
        tr.appendChild(el("td", {}, (w.counts.FINISHED || 0) + "/" + w.task_count));
        tr.appendChild(el("td", {}, w.host || ""));
        tr.appendChild(el("td", {}, when(w.updated_at)));
        tr.addEventListener("click", function (ev) { if (ev.target === tr || ev.target.tagName === "TD") select(w.id); });
        tbody.appendChild(tr);
      });
    }).catch(function () {});
  }

  function layout(graph) {
    var names = graph.nodes.map(function (n) { return n.id; });
    var external = {};
    graph.edges.forEach(function (e) { if (e.transversal) external[e.source] = true; });
    var all = names.concat(Object.keys(external));
    var prevs = {}; all.forEach(function (n) { prevs[n] = []; });
    graph.edges.forEach(function (e) { prevs[e.target].push(e.source); });
    var depth = {}, visiting = {};
    function d(n) {
      if (depth[n] !== undefined) return depth[n];
      if (visiting[n]) return 0; // tolerate cycles in malformed documents
      visiting[n] = true;
      var v = prevs[n].length ? 1 + Math.max.apply(null, prevs[n].map(d)) : 0;
      visiting[n] = false; depth[n] = v; return v;
    }
    var columns = [];
    all.forEach(function (n) { var c = d(n); (columns[c] = columns[c] || []).push(n); });
    var pos = {}, W = 150, H = 34, GX = 60, GY = 18;
    columns.forEach(function (col, ci) { col.forEach(function (n, ri) { pos[n] = { x: 10 + ci * (W + GX), y: 10 + ri * (H + GY) }; }); });
    var rows = Math.max.apply(null, columns.map(function (c) { return c.length; }).concat([1]));
    return { pos: pos, external: external, W: W, H: H,
      width: 20 + columns.length * (W + GX) - GX, height: 20 + rows * (H + GY) - GY };
  }

  function drawGraph(graph) {
    var root = document.getElementById("graph");
    Array.prototype.slice.call(root.childNodes).forEach(function (child) {
      if (child.nodeName.toLowerCase() === "g") root.removeChild(child);
    });
    var L = layout(graph), status = {};
    graph.nodes.forEach(function (n) { status[n.id] = n.status; });
    root.setAttribute("width", L.width); root.setAttribute("height", L.height);
    root.setAttribute("viewBox", "0 0 " + L.width + " " + L.height);
    var defs = svg("g"), edges = svg("g"), nodes = svg("g");
    var marker = svg("marker", { id: "arrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
      markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
    marker.appendChild(svg("path", { d: "M0,0 L10,5 L0,10 z", "class": "arrow" }));
    var defsEl = svg("defs"); defsEl.appendChild(marker); defs.appendChild(defsEl);
    graph.edges.forEach(function (e) {
      var a = L.pos[e.source], b = L.pos[e.target]; if (!a || !b) return;
      var x1 = a.x + L.W, y1 = a.y + L.H / 2, x2 = b.x, y2 = b.y + L.H / 2, mx = (x1 + x2) / 2;
      edges.appendChild(svg("path", { "class": "edge" + (e.transversal ? " transversal" : ""),
        "marker-end": "url(#arrow)",
        d: "M" + x1 + "," + y1 + " C" + mx + "," + y1 + " " + mx + "," + y2 + " " + x2 + "," + y2 }));
    });
    Object.keys(L.pos).forEach(function (n) {
      var p = L.pos[n], g = svg("g", { "class": "node", transform: "translate(" + p.x + "," + p.y + ")" });
      var s = status[n] || "READY";
      var rect = svg("rect", { width: L.W, height: L.H, rx: 6, "class": "s-" + s, stroke: "currentColor" });
      if (L.external[n]) rect.setAttribute("stroke-dasharray", "4 3");
      var label = svg("text", { x: 8, y: L.H / 2 + 4 });
      label.textContent = (n.length > 20 ? n.slice(0, 19) + "…" : n) + (L.external[n] ? " ↗" : "");
      var title = svg("title"); title.textContent = n + (L.external[n] ? " (task of another workflow)" : " — " + s);
      g.appendChild(title); g.appendChild(rect); g.appendChild(label); nodes.appendChild(g);
    });
    root.appendChild(defs); root.appendChild(edges); root.appendChild(nodes);
  }

  function loadDetail() {
    var id = state.selected; if (!id) return Promise.resolve();
    return Promise.all([api("/api/v1/workflows/" + id + "?history=false"), api("/api/v1/workflows/" + id + "/graph")])
      .then(function (res) {
        var w = res[0];
        var sig = JSON.stringify(res);
        if (sig === state.detailSig) return;
        state.detailSig = sig;
        document.getElementById("detail").hidden = false;
        var title = document.getElementById("detail-title"); clear(title);
        title.appendChild(document.createTextNode(w.name + " ")); title.appendChild(badge(w.status));
        document.getElementById("detail-meta").textContent =
          "id " + w.id + " · host " + (w.host || "—") + " · created " + when(w.created_at);
        document.getElementById("download").href = "/api/v1/workflows/" + id + "/document?download=1";
        drawGraph(res[1]);
        var tbody = document.getElementById("tasks"); clear(tbody);
        Object.keys(w.tasks).forEach(function (name) {
          var t = w.tasks[name], tr = el("tr");
          tr.appendChild(el("td", {}, name)); tr.appendChild(el("td", {}, t.type));
          var st = el("td"); st.appendChild(badge(t.status)); tr.appendChild(st);
          tr.appendChild(el("td", {}, (t.prevs || []).join(", ")));
          tr.appendChild(el("td", { "class": "path" }, t.working_dir || ""));
          tbody.appendChild(tr);
        });
      }).catch(function (e) {
        if (String(e.message).indexOf("does not exist") >= 0) { state.selected = null; document.getElementById("detail").hidden = true; }
      });
  }

  function loadEvents() {
    var id = state.selected; if (!id) return;
    var q = state.lastEvent ? "?after=" + encodeURIComponent(state.lastEvent) : "";
    api("/api/v1/workflows/" + id + "/events" + q).then(function (data) {
      if (id !== state.selected) return;
      var list = document.getElementById("events");
      data.items.forEach(function (ev) {
        var text = when(ev.at) + " · " + ev.kind + (ev.task ? " · " + ev.task : "") + (ev.status ? " → " + ev.status : "");
        list.insertBefore(el("li", {}, text), list.firstChild);
      });
      state.lastEvent = data.last;
    }).catch(function () {});
  }

  function select(id) {
    state.selected = id; state.lastEvent = null; state.detailSig = "";
    clear(document.getElementById("events"));
    Array.prototype.forEach.call(document.querySelectorAll("#workflows tr[data-id]"), function (tr) {
      tr.setAttribute("aria-selected", String(tr.dataset.id === id));
    });
    loadDetail(); loadEvents();
    document.getElementById("detail").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function tick() { loadHealth(); loadList(); loadDetail(); loadEvents(); }

  document.getElementById("filter").addEventListener("input", loadList);
  document.getElementById("status-filter").addEventListener("change", loadList);
  document.getElementById("token-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    try { sessionStorage.setItem(TOKEN_KEY, document.getElementById("token").value); } catch (e) {}
    document.getElementById("token-form").hidden = true; tick();
  });
  if (body.dataset.protectReads === "true" && !token()) document.getElementById("token-form").hidden = false;
  tick();
  state.timer = setInterval(function () { if (!document.hidden) tick(); }, refreshMs);
})();
