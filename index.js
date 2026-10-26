// Toronto Parks landing page: preview map + copy buttons.

(function () {
  "use strict";

  function initMap() {
    var el = document.getElementById("preview-map");
    if (!el || typeof L === "undefined" || !el.dataset.rasterUrl) {
      return;
    }

    var map = L.map(el, { minZoom: 11, maxZoom: 19 }).setView(
      [43.7001, -79.3845], 13
    );

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">' +
        "OpenStreetMap</a> contributors",
    }).addTo(map);

    L.tileLayer(el.dataset.rasterUrl, {
      minZoom: 13,
      maxNativeZoom: 17,
      maxZoom: 19,
    }).addTo(map);
  }

  function initCopyButtons() {
    var blocks = document.querySelectorAll("pre.url");
    Array.prototype.forEach.call(blocks, function (pre) {
      var wrap = document.createElement("div");
      wrap.className = "url-wrap";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.textContent = "Copy";
      wrap.appendChild(btn);

      btn.addEventListener("click", function () {
        navigator.clipboard.writeText(pre.textContent).then(
          function () {
            flash(btn, "Copied");
          },
          function () {
            flash(btn, "Press Ctrl+C");
          }
        );
      });
    });
  }

  function flash(btn, message) {
    btn.textContent = message;
    setTimeout(function () {
      btn.textContent = "Copy";
    }, 1500);
  }

  document.addEventListener("DOMContentLoaded", function () {
    initMap();
    initCopyButtons();
  });
})();
