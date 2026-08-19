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
