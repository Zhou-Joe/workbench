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
})();
