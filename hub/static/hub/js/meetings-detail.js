/* Meeting detail: streamed summary generation + client-side exports.
 * Export formats ported from the proven MeetingAssistant export.ts. */
(function () {
  const dataEl = document.getElementById("meeting-data");
  const summarizeBtn = document.getElementById("summarize-btn");
  const summaryEl = document.getElementById("summary-text");
  const exportRow = document.getElementById("export-row");

  const DATA = dataEl ? JSON.parse(dataEl.textContent) : null;

  if (summarizeBtn && summaryEl && DATA) {
    summarizeBtn.addEventListener("click", async () => {
      summarizeBtn.disabled = true;
      summarizeBtn.textContent = "Summarizing…";
      summaryEl.textContent = "";
      try {
        await window.RPH.streamSummary(`/meetings/${DATA.id}/summarize-stream/`, summaryEl);
      } catch (e) {
        summaryEl.textContent = "Summary failed: " + (e.message || e);
      }
      summarizeBtn.disabled = false;
      summarizeBtn.textContent = "Summarize";
      // Refresh the page region so the persisted summary + status round-trip.
      document.body.dispatchEvent(new CustomEvent("rph:tick"));
    });
  }

  if (exportRow && DATA) {
    exportRow.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-export]");
      if (!btn) return;
      const format = btn.dataset.export;
      const content = buildExport(format, DATA, DATA.utterances);
      const mime = format === "html" ? "text/html" : format === "json" ? "application/json" : "text/plain";
      const blob = new Blob([content], { type: mime + ";charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = exportFilename(DATA, format);
      a.click();
      URL.revokeObjectURL(a.href);
    });
  }

  // ---- formats (ported) ---------------------------------------------------
  const LANG_LABEL = { zh: "中文", en: "EN", mixed: "EN/中文", unknown: "" };

  function fmtTs(seconds) {
    if (seconds == null) return "";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `[${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}]`;
  }

  function srtTs(seconds) {
    const t = Math.max(0, seconds || 0);
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = Math.floor(t % 60);
    const ms = Math.floor((t - Math.floor(t)) * 1000);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
  }

  function speakerOf(u) {
    return (u.speaker_label || "").trim() || "Speaker";
  }

  function esc(s) {
    return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function buildExport(format, meeting, utterances) {
    switch (format) {
      case "txt":
        return toTxt(meeting, utterances);
      case "md":
        return toMd(meeting, utterances);
      case "srt":
        return toSrt(utterances);
      case "html":
        return toHtml(meeting, utterances);
      case "json":
        return JSON.stringify(meeting, null, 2);
      default:
        return "";
    }
  }

  function toTxt(meeting, utterances) {
    const lines = [`${meeting.title} — ${meeting.date}`, ""];
    for (const u of utterances) {
      const lang = LANG_LABEL[u.lang] ? ` (${LANG_LABEL[u.lang]})` : "";
      lines.push(`${fmtTs(u.start_ts)} ${speakerOf(u)}:${lang} ${u.text}`);
      if (u.translation) lines.push(`    ↳ ${u.translation}`);
    }
    return lines.join("\n") + "\n";
  }

  function toMd(meeting, utterances) {
    const lines = [`# ${meeting.title}`, "", `*${meeting.date}*`, ""];
    let current = null;
    for (const u of utterances) {
      const spk = speakerOf(u);
      if (spk !== current) {
        lines.push(`**${spk}**`, "");
        current = spk;
      }
      lines.push(u.text);
      if (u.translation) lines.push("", `> ${u.translation}`);
      lines.push("");
    }
    return lines.join("\n");
  }

  function toSrt(utterances) {
    const lines = [];
    utterances.forEach((u, i) => {
      lines.push(String(i + 1));
      lines.push(`${srtTs(u.start_ts)} --> ${srtTs(u.end_ts ?? u.start_ts)}`);
      lines.push(`${speakerOf(u)}: ${u.text}`);
      if (u.translation) lines.push(u.translation);
      lines.push("");
    });
    return lines.join("\n");
  }

  function toHtml(meeting, utterances) {
    const palette = ["#FF4F00", "#0A7B5F", "#B1006E", "#0057D8", "#7A5C00"];
    const speakers = [...new Set(utterances.map(speakerOf))];
    const colorOf = (spk) => palette[speakers.indexOf(spk) % palette.length];
    const rows = utterances
      .map(
        (u) => `<div class="utt">
  <span class="spk" style="color:${colorOf(speakerOf(u))}">${esc(speakerOf(u))}</span>
  <span class="time">${esc(fmtTs(u.start_ts))}</span>
  <span class="text">${esc(u.text)}</span>
  ${u.translation ? `<blockquote>${esc(u.translation)}</blockquote>` : ""}
</div>`
      )
      .join("\n");
    return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(meeting.title)}</title>
<style>body{font-family:Helvetica,Arial,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;line-height:1.5}
.utt{margin:.4rem 0}.spk{font-weight:700;margin-right:.6rem}.time{color:#888;font-size:.85rem;margin-right:.6rem}
blockquote{margin:.1rem 0 .4rem 2rem;color:#555;border-left:3px solid #ddd;padding-left:.8rem}</style>
</head><body><h1>${esc(meeting.title)}</h1><p>${esc(meeting.date)}</p>
${rows}</body></html>`;
  }

  function exportFilename(meeting, format) {
    const slug = (meeting.title || "meeting")
      .toLowerCase()
      .replace(/[^\w\u4e00-\u9fff]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60);
    return `meeting-${slug}.${format}`;
  }
})();
