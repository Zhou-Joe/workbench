/* Ride Program Hub — SSE bridge.
   The backend publishes pipeline events to /events/; each message becomes a
   `rph:tick` custom event on <body>, which htmx regions listen for via
   hx-trigger="rph:tick from:body". The activity strip in the masthead
   narrates what just happened. */

(function () {
  "use strict";

  var LABELS = {
    document: {
      detected: "file detected",
      processing: "extracting",
      extracted: "text extracted",
      milestones: "milestones extracted",
      failed: "extraction failed",
    },
    digest: "phase digest updated",
    revision: "revision updated",
    phase: "phases changed",
    project: "project added",
    settings: "settings changed",
  };

  var activityTimer = null;

  function describe(data) {
    if (data.type === "document" && LABELS.document[data.state]) {
      return (data.filename ? data.filename + " — " : "") + LABELS.document[data.state];
    }
    return LABELS[data.type] || data.type;
  }

  function showActivity(text) {
    var el = document.getElementById("activity");
    if (!el) return;
    el.textContent = text;
    el.classList.add("on");
    if (activityTimer) clearTimeout(activityTimer);
    activityTimer = setTimeout(function () {
      el.textContent = "";
      el.classList.remove("on");
    }, 5000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!window.EventSource) return;
    var es = new EventSource("/events/");
    es.onmessage = function (e) {
      var data;
      try {
        data = JSON.parse(e.data);
      } catch (err) {
        return;
      }
      document.body.dispatchEvent(
        new CustomEvent("rph:tick", { detail: data, bubbles: false })
      );
      showActivity(describe(data));
    };
  });

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function wireDropzone(zone) {
    var url = zone.getAttribute("data-dropzone");
    var input = zone.querySelector('input[type="file"]');
    var status = zone.querySelector(".dropzone-status");

    function upload(fileList) {
      var fd = new FormData();
      Array.prototype.forEach.call(fileList, function (f) {
        fd.append("files", f);
      });
      var folderInput = zone.querySelector('input[name="folder"]');
      if (folderInput && folderInput.value.trim()) {
        fd.append("folder", folderInput.value.trim());
      }
      fd.append("path", zone.getAttribute("data-path") || "");
      status.textContent =
        "uploading " + fileList.length + " file" +
        (fileList.length > 1 ? "s" : "") + "…";
      fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        body: fd,
        credentials: "same-origin",
      })
        .then(function (r) {
          if (!r.ok) {
            return r.text().then(function (t) {
              throw new Error(t.slice(0, 140) || "HTTP " + r.status);
            });
          }
          status.textContent = "uploaded — extraction starting";
          document.body.dispatchEvent(new CustomEvent("rph:tick"));
        })
        .catch(function (err) {
          status.textContent = "upload failed: " + err.message;
        });
    }

    if (zone.dataset.wired) return;
    zone.dataset.wired = "1";

    zone.addEventListener("dragover", function (e) {
      e.preventDefault();
      zone.classList.add("drag");
    });
    zone.addEventListener("dragleave", function () {
      zone.classList.remove("drag");
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      zone.classList.remove("drag");
      if (e.dataTransfer && e.dataTransfer.files.length) {
        upload(e.dataTransfer.files);
      }
    });
    if (input) {
      input.addEventListener("change", function () {
        if (input.files.length) upload(input.files);
        input.value = "";
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-dropzone]").forEach(wireDropzone);
  });

  // ---------- ⌘K command palette ----------

  var paletteItems = null;

  function paletteToggle(show) {
    var overlay = document.getElementById("palette");
    var input = document.getElementById("palette-input");
    if (!overlay || !input) return;
    if (show === undefined) show = overlay.hidden;
    overlay.hidden = !show;
    if (show) {
      input.value = "";
      paletteRender("");
      input.focus();
    }
  }

  function paletteRender(query) {
    if (paletteItems === null) return;
    var q = query.trim().toLowerCase();
    var list = document.getElementById("palette-list");
    list.innerHTML = "";
    var matches = paletteItems
      .filter(function (item) {
        return !q || item.label.toLowerCase().indexOf(q) >= 0;
      })
      .slice(0, 12);
    matches.forEach(function (item, i) {
      var li = document.createElement("li");
      li.textContent = item.label;
      li.dataset.url = item.url;
      li.className = i === 0 ? "palette-active" : "";
      li.addEventListener("click", function () {
        window.location.href = item.url;
      });
      list.appendChild(li);
    });
  }

  function paletteMove(delta) {
    var list = document.getElementById("palette-list");
    var items = Array.prototype.slice.call(list.children);
    if (!items.length) return;
    var idx = items.findIndex(function (li) {
      return li.classList.contains("palette-active");
    });
    items[idx] && items[idx].classList.remove("palette-active");
    var next = Math.min(Math.max(idx + delta, 0), items.length - 1);
    items[next].classList.add("palette-active");
    items[next].scrollIntoView({ block: "nearest" });
  }

  document.addEventListener("DOMContentLoaded", function () {
    fetch("/palette/")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        paletteItems = data.items || [];
      })
      .catch(function () {});
  });

  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      paletteToggle();
      return;
    }
    var overlay = document.getElementById("palette");
    if (!overlay || overlay.hidden) return;
    if (e.key === "Escape") {
      paletteToggle(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      paletteMove(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      paletteMove(-1);
    } else if (e.key === "Enter") {
      var active = document.querySelector("#palette-list .palette-active");
      if (active) window.location.href = active.dataset.url;
    }
  });

  document.addEventListener("input", function (e) {
    if (e.target && e.target.id === "palette-input") {
      paletteRender(e.target.value);
    }
  });

  document.addEventListener("click", function (e) {
    var overlay = document.getElementById("palette");
    if (overlay && !overlay.hidden && e.target === overlay) {
      paletteToggle(false);
    }
  });

  // phase-body regions are replaced by htmx swaps — re-wire their drop zones
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && e.target.querySelectorAll) {
      e.target.querySelectorAll("[data-dropzone]").forEach(function (zone) {
        if (!zone.dataset.wired) {
          zone.dataset.wired = "1";
          wireDropzone(zone);
        }
      });
    }
  });
})();

/* Shared helper: read an SSE endpoint that streams `data: <delta>` lines and
   append them into `target`. Resolves on [DONE]. Used by the meeting summary
   and series overview streams. */
window.RPH = window.RPH || {};
window.RPH.streamSummary = async function (url, target) {
  const resp = await fetch(url, { headers: { Accept: "text/event-stream" } });
  if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (data === "[DONE]") return;
      target.append(data);
    }
  }
};
