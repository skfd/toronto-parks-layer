// Gap history page: a three-series line chart of the recorded compare runs,
// drawn as inline SVG from the rows embedded in the page. Same colours as the
// gap map's markers, so "missing" is the same purple here and there.

(function () {
  "use strict";

  var SERIES = [
    { key: "missing", label: "Missing in OSM", short: "missing", color: "#7048e8" },
    { key: "mismatch", label: "Name mismatch", short: "name mismatch", color: "#1c7ed6" },
    { key: "unnamed", label: "OSM area unnamed", short: "unnamed", color: "#e8590c" },
  ];
  var W = 860, H = 320;
  var M = { top: 16, right: 150, bottom: 36, left: 48 };
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var NS = "http://www.w3.org/2000/svg";

  function init() {
    var holder = document.getElementById("chart");
    var raw = document.getElementById("history-data");
    var rows = [];
    try { rows = JSON.parse(raw.textContent) || []; } catch (e) { rows = []; }
    legend(document.getElementById("legend"));
    if (!rows.length) {
      var p = document.createElement("p");
      p.className = "empty";
      p.textContent = "No comparisons recorded yet. The first weekly build " +
        "adds a point; `python run.py backfill` reconstructs earlier weeks.";
      holder.appendChild(p);
      return;
    }
    draw(holder, rows);
  }

  function legend(el) {
    SERIES.forEach(function (s) {
      var span = document.createElement("span");
      var i = document.createElement("i");
      i.style.borderColor = s.color;
      span.appendChild(i);
      span.appendChild(document.createTextNode(s.label));
      el.appendChild(span);
    });
    var a = document.createElement("span");
    a.className = "attic";
    a.appendChild(document.createElement("i"));
    a.appendChild(document.createTextNode("shaded: reconstructed from OSM history"));
    el.appendChild(a);
  }

  function draw(holder, rows) {
    var xs = rows.map(function (r) { return Date.parse(r.date + "T00:00:00Z"); });
    var x0 = xs[0], x1 = xs[xs.length - 1];
    if (x1 === x0) { x0 -= 7 * 864e5; x1 += 7 * 864e5; }
    var maxY = 0;
    rows.forEach(function (r) {
      SERIES.forEach(function (s) { maxY = Math.max(maxY, r[s.key] || 0); });
    });
    var step = niceStep(maxY || 1);
    var yTop = Math.max(step, Math.ceil(maxY / step) * step);
    var plotW = W - M.left - M.right, plotH = H - M.top - M.bottom;
    var sx = function (t) { return M.left + (t - x0) / (x1 - x0) * plotW; };
    var sy = function (v) { return M.top + plotH - v / yTop * plotH; };

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Gap counts per comparison run; the table below has the values" });

    // Shade each run of reconstructed weeks, so the chart says which points
    // the weekly build saw and which were rebuilt from OSM's history.
    atticSpans(rows).forEach(function (span) {
      var a = sx(xs[span[0]]) - (span[0] ? 0 : 6);
      var b = sx(xs[span[1]]) + (span[1] === rows.length - 1 ? 6 : 0);
      svg.appendChild(el("rect", { "class": "attic-band", x: a, y: M.top,
        width: Math.max(b - a, 4), height: plotH }));
    });

    // Gridlines + y ticks (recessive), x ticks at month starts.
    for (var v = 0; v <= yTop; v += step) {
      svg.appendChild(el("line", { "class": "grid", x1: M.left, x2: W - M.right,
        y1: sy(v), y2: sy(v) }));
      svg.appendChild(text(M.left - 8, sy(v) + 4, fmt(v), "axis", "end"));
    }
    monthStarts(x0, x1).forEach(function (t) {
      var d = new Date(t);
      var label = MONTHS[d.getUTCMonth()] +
        (d.getUTCMonth() === 0 || t === monthStarts(x0, x1)[0] ? " " + d.getUTCFullYear() : "");
      svg.appendChild(el("line", { "class": "grid", x1: sx(t), x2: sx(t),
        y1: M.top + plotH, y2: M.top + plotH + 5 }));
      svg.appendChild(text(sx(t), M.top + plotH + 20, label, "axis", "middle"));
    });

    // Lines, then points (a 2px surface ring keeps them legible where they cross).
    SERIES.forEach(function (s) {
      var d = rows.map(function (r, i) {
        return (i ? "L" : "M") + sx(xs[i]).toFixed(1) + " " + sy(r[s.key] || 0).toFixed(1);
      }).join(" ");
      svg.appendChild(el("path", { "class": "series", d: d, stroke: s.color }));
    });
    SERIES.forEach(function (s) {
      rows.forEach(function (r, i) {
        svg.appendChild(el("circle", { "class": "pt", r: 4, fill: s.color,
          cx: sx(xs[i]), cy: sy(r[s.key] || 0) }));
      });
    });

    // Direct end labels: the latest value of each series, nudged apart.
    var last = rows[rows.length - 1];
    var ends = SERIES.map(function (s) {
      return { s: s, y: sy(last[s.key] || 0), v: last[s.key] || 0 };
    }).sort(function (a, b) { return a.y - b.y; });
    for (var i = 1; i < ends.length; i++) {
      if (ends[i].y - ends[i - 1].y < 16) { ends[i].y = ends[i - 1].y + 16; }
    }
    ends.forEach(function (e) {
      var x = W - M.right + 10;
      svg.appendChild(el("line", { x1: x, x2: x + 14, y1: e.y, y2: e.y,
        stroke: e.s.color, "stroke-width": 2, "stroke-linecap": "round" }));
      svg.appendChild(text(x + 20, e.y + 4, fmt(e.v) + " " + e.s.short,
        "end-label", "start"));
    });

    // Hover: a crosshair snapping to the nearest run, one tooltip for all series.
    var cross = el("line", { "class": "crosshair", y1: M.top, y2: M.top + plotH,
      x1: -10, x2: -10, visibility: "hidden" });
    svg.appendChild(cross);
    var hit = el("rect", { "class": "hit", x: M.left, y: M.top, width: plotW, height: plotH });
    svg.appendChild(hit);
    holder.appendChild(svg);
    var tip = document.getElementById("tip");

    function nearest(clientX) {
      var box = svg.getBoundingClientRect();
      var px = (clientX - box.left) / box.width * W;
      var best = 0, bestD = Infinity;
      xs.forEach(function (t, i) {
        var d = Math.abs(sx(t) - px);
        if (d < bestD) { bestD = d; best = i; }
      });
      return best;
    }
    function show(i, clientX, clientY) {
      var r = rows[i];
      cross.setAttribute("x1", sx(xs[i]));
      cross.setAttribute("x2", sx(xs[i]));
      cross.setAttribute("visibility", "visible");
      while (tip.firstChild) { tip.removeChild(tip.firstChild); }
      var head = document.createElement("div");
      head.className = "d";
      head.textContent = r.date + (r.source === "attic" ? " (reconstructed)" : "") +
        (r.osm_date && r.osm_date !== r.date ? " · OSM " + r.osm_date : "");
      tip.appendChild(head);
      SERIES.forEach(function (s) {
        var line = document.createElement("div");
        var key = document.createElement("i");
        key.style.borderColor = s.color;
        var val = document.createElement("strong");
        val.textContent = fmt(r[s.key] || 0);
        line.appendChild(key);
        line.appendChild(val);
        line.appendChild(document.createTextNode(" " + s.short));
        tip.appendChild(line);
      });
      var hb = holder.getBoundingClientRect();
      tip.style.display = "block";
      var left = clientX - hb.left + 14, top = clientY - hb.top - 10;
      if (left + tip.offsetWidth > hb.width) { left = clientX - hb.left - tip.offsetWidth - 14; }
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = Math.max(0, top) + "px";
    }
    hit.addEventListener("pointermove", function (ev) { show(nearest(ev.clientX), ev.clientX, ev.clientY); });
    hit.addEventListener("pointerleave", function () {
      tip.style.display = "none";
      cross.setAttribute("visibility", "hidden");
    });
  }

  // [first, last] row-index pairs of each contiguous run of reconstructed rows.
  function atticSpans(rows) {
    var spans = [], start = null;
    rows.forEach(function (r, i) {
      if (r.source === "attic") {
        if (start === null) { start = i; }
      } else if (start !== null) {
        spans.push([start, i - 1]);
        start = null;
      }
    });
    if (start !== null) { spans.push([start, rows.length - 1]); }
    return spans;
  }

  function monthStarts(t0, t1) {
    var out = [];
    var d = new Date(t0);
    d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
    while (d.getTime() <= t1) {
      out.push(d.getTime());
      d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
    }
    if (!out.length) { out.push(t0, t1); }
    return out;
  }

  function niceStep(max) {
    var raw = max / 4, pow = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var f = raw / pow;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow;
  }

  function fmt(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

  function el(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }

  function text(x, y, s, cls, anchor) {
    var t = el("text", { x: x, y: y, "class": cls, "text-anchor": anchor });
    t.textContent = s;
    return t;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
