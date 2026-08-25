/* Series detail: streamed cross-meeting progress overview. */
(function () {
  const btn = document.getElementById("summarize-btn");
  const target = document.getElementById("summary-text");
  const id = document.getElementById("series-page");
  if (!btn || !target || !id) return;
  const seriesId = id.dataset.seriesId;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Summarizing…";
    target.textContent = "";
    try {
      await window.RPH.streamSummary(`/meetings/series/${seriesId}/summarize-stream/`, target);
    } catch (e) {
      target.textContent = "Overview failed: " + (e.message || e);
    }
    btn.disabled = false;
    btn.textContent = "Progress overview";
    document.body.dispatchEvent(new CustomEvent("rph:tick"));
  });
})();
