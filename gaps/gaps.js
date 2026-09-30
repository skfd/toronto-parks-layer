// Gap-review page: City raster layer + gap markers, driven by a side table.

(function () {
  "use strict";

  var COLORS = {
    missing: "#7048e8", mismatch: "#1c7ed6", unnamed: "#e8590c", trca: "#868e96",
  };
  var map;
  var features = [];
  var markers = [];      // CircleMarker per feature, indexed like features
  var highlight = null;  // outline of the currently selected gap
  var selectedRow = null;
  var selectedIndex = null;  // feature index of the current selection

  function init() {
    var el = document.getElementById("gap-map");
    if (!el || typeof L === "undefined" || !el.dataset.geojson) {
      return;
    }
    map = L.map(el).setView([43.7001, -79.3845], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">' +
        "OpenStreetMap</a> contributors",
    }).addTo(map);
    if (el.dataset.raster) {
      L.tileLayer(el.dataset.raster, {
        minZoom: 13, maxNativeZoom: 17, maxZoom: 19, opacity: 0.85,
      }).addTo(map);
    }

    fetch(el.dataset.geojson)
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function (e) {
        el.innerHTML = '<p style="padding:1rem">Could not load gaps.geojson.</p>';
        console.error(e);
      });
  }

  function render(data) {
    features = data.features || [];

    features.forEach(function (f, i) {
      f.properties._i = i;
      var center = centroid(f.geometry);
      f._center = center;
      var m = L.circleMarker(center, {
        radius: 6,
        color: "#fff",
        weight: 1,
        fillColor: COLORS[f.properties.status] || "#888",
        fillOpacity: 0.95,
      });
      m.bindPopup(popupHtml(f));
      m.on("click", function () { select(i, false); });
      m.addTo(map);
      markers[i] = m;
    });

    buildTable();
    wireControls();
  }

  // Centroid of a (Multi)Polygon's first/largest outer ring -> [lat, lng].
  function centroid(geom) {
    var rings = geom.type === "Polygon"
      ? [geom.coordinates[0]]
      : geom.coordinates.map(function (poly) { return poly[0]; });
    var best = rings[0], bestArea = -1;
    rings.forEach(function (r) {
      var a = Math.abs(ringArea(r));
      if (a > bestArea) { bestArea = a; best = r; }
    });
    var n = best.length, area = 0, cx = 0, cy = 0;
    for (var i = 0; i < n; i++) {
      var p0 = best[i], p1 = best[(i + 1) % n];
      var cross = p0[0] * p1[1] - p1[0] * p0[1];
      area += cross;
      cx += (p0[0] + p1[0]) * cross;
      cy += (p0[1] + p1[1]) * cross;
    }
    if (area === 0) {
      var sx = 0, sy = 0;
      best.forEach(function (p) { sx += p[0]; sy += p[1]; });
      return [sy / n, sx / n];
    }
    area *= 0.5;
    return [cy / (6 * area), cx / (6 * area)];
  }

  function ringArea(r) {
    var a = 0, n = r.length;
    for (var i = 0; i < n; i++) {
      var p0 = r[i], p1 = r[(i + 1) % n];
      a += p0[0] * p1[1] - p1[0] * p0[1];
    }
    return a / 2;
  }

  // Where to send the user for a feature: the openstreetmap.org view and the
  // iD editor. Points at the existing way when there is one, else the centroid.
  function osmTargets(f) {
    var p = f.properties;
    var m = p.osm_url && p.osm_url.match(/(node|way|relation)\/(\d+)/);
    if (m) {
      return {
        osm: p.osm_url,
        id: "https://www.openstreetmap.org/edit?" + m[1] + "=" + m[2],
      };
    }
    var c = f._center;
    if (!c) { return null; }
    var ll = c[0].toFixed(5) + "/" + c[1].toFixed(5);
    return {
      osm: "https://www.openstreetmap.org/#map=18/" + ll,
      id: "https://www.openstreetmap.org/edit#map=18/" + ll,
    };
  }

  // "OSM · iD" link pair shared by the table and the popups.
  function osmPairHtml(f) {
    var t = osmTargets(f);
    if (!t) { return ""; }
    return '<a href="' + t.osm + '" target="_blank" rel="noopener" ' +
      'title="View on openstreetmap.org (hotkey: O)">OSM</a> &middot; ' +
      '<a href="' + t.id + '" target="_blank" rel="noopener" ' +
      'title="Open in the iD editor (hotkey: I)">iD</a>';
  }

  function popupHtml(f) {
    var p = f.properties;
    var h = "<strong>" + esc(p.name || "(unnamed)") + "</strong><br>" +
      esc(p["class"]) + " &middot; " + p.status;
    if (p.status === "mismatch") {
      h += "<br>OSM name: " + (p.osm_name ? esc(p.osm_name) : "<em>none</em>");
    }
    var links = osmPairHtml(f);
    if (links) { h += "<br>" + links; }
    return h;
  }

  function buildTable() {
    var tbody = document.querySelector("#gap-table tbody");
    var rows = features.slice().sort(function (a, b) {
      return (a.properties.name || "").localeCompare(b.properties.name || "");
    });
    tbody.innerHTML = rows.map(function (f) {
      var p = f.properties;
      var links = osmPairHtml(f);
      var osm = links
        ? (p.osm_name ? '<span class="osm-name">' + esc(p.osm_name) + "</span>" : "") +
          '<span class="osm-links">' + links + "</span>"
        : '<span class="osm-blank">&mdash;</span>';
      return '<tr data-i="' + p._i + '" data-status="' + p.status +
        '" data-name="' + esc((p.name || "").toLowerCase()) + '">' +
        "<td>" + esc(p.name || "(unnamed)") + "</td>" +
        "<td>" + esc(p["class"]) + "</td>" +
        '<td class="status-' + p.status + '">' + p.status + "</td>" +
        "<td>" + osm + "</td></tr>";
    }).join("");

    tbody.addEventListener("click", function (ev) {
      if (ev.target.closest("a")) { return; }  // let OSM links work
      var tr = ev.target.closest("tr");
      if (tr) { select(parseInt(tr.dataset.i, 10), true); }
    });
  }

  // Select a gap: outline it, fit the map, open its popup, mark its row.
  function select(i, fromTable) {
    var f = features[i];
    if (!f) { return; }
    selectedIndex = i;

    if (highlight) { map.removeLayer(highlight); }
    highlight = L.geoJSON(f, {
      style: { color: "#0a7", weight: 3, fill: false },
    }).addTo(map);
    map.fitBounds(highlight.getBounds(), { maxZoom: 17, padding: [40, 40] });
    if (markers[i]) { markers[i].openPopup(); }

    if (selectedRow) { selectedRow.classList.remove("selected"); }
    var tr = document.querySelector('#gap-table tr[data-i="' + i + '"]');
    if (tr) {
      tr.classList.add("selected");
      selectedRow = tr;
      if (!fromTable) { tr.scrollIntoView({ block: "center" }); }
    }
  }

  function wireControls() {
    var boxes = {
      missing: document.getElementById("show-missing"),
      mismatch: document.getElementById("show-mismatch"),
      unnamed: document.getElementById("show-unnamed"),
      trca: document.getElementById("show-trca"),
    };
    var filter = document.getElementById("filter");

    function statusOn(status) {
      var b = boxes[status];
      return b ? b.checked : true;
    }

    function apply() {
      var q = filter.value.trim().toLowerCase();

      features.forEach(function (f) {
        var p = f.properties;
        var hit = statusOn(p.status) &&
          (!q || (p.name || "").toLowerCase().indexOf(q) > -1);
        var m = markers[p._i];
        if (hit && !map.hasLayer(m)) { map.addLayer(m); }
        else if (!hit && map.hasLayer(m)) { map.removeLayer(m); }
      });

      var rows = document.querySelectorAll("#gap-table tbody tr");
      Array.prototype.forEach.call(rows, function (tr) {
        var hit = statusOn(tr.dataset.status) &&
          (!q || tr.dataset.name.indexOf(q) > -1);
        tr.style.display = hit ? "" : "none";
      });
    }

    Object.keys(boxes).forEach(function (k) {
      if (boxes[k]) { boxes[k].addEventListener("change", apply); }
    });
    filter.addEventListener("input", apply);
    apply();

    // O / I open the selected gap on openstreetmap.org / in the iD editor.
    document.addEventListener("keydown", function (ev) {
      if (ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
      if (/^(input|textarea|select)$/i.test(ev.target.tagName)) { return; }
      var key = ev.key.toLowerCase();
      if (key !== "o" && key !== "i") { return; }
      if (selectedIndex == null) { return; }
      var t = osmTargets(features[selectedIndex]);
      if (!t) { return; }
      ev.preventDefault();
      window.open(key === "o" ? t.osm : t.id, "_blank", "noopener");
    });
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
