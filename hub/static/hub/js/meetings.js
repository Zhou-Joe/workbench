/* Live meeting session — mic/system-audio capture + WS transcript client.
 * Ported from the proven MeetingAssistant hooks (useAudioCapture /
 * useLiveTranscript) to plain JS, no build step. */
(function () {
  const root = document.getElementById("live-root");
  if (!root) return;

  const setup = document.getElementById("live-setup");
  const run = document.getElementById("live-run");
  const startForm = document.getElementById("live-start-form");
  const micBtn = document.getElementById("live-mic");
  const sysBtn = document.getElementById("live-sys");
  const translateBtn = document.getElementById("live-translate");
  const stopBtn = document.getElementById("live-stop");
  const levelFill = document.getElementById("live-level");
  const statusEl = document.getElementById("live-status");
  const transcriptEl = document.getElementById("live-transcript");

  let ws = null;
  let meetingId = null;
  let retries = 0;
  let intentionalClose = false;
  let translateOn = true;
  let partialEl = null;

  // ---- audio capture ----------------------------------------------------
  let ctx = null;
  let streams = [];
  let nodes = [];
  let proc = null;

  async function startCapture(sources) {
    stopCapture();
    const acquired = [];
    try {
      if (sources.includes("mic")) {
        acquired.push(
          await navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
          })
        );
      }
      if (sources.includes("display")) {
        const display = await navigator.mediaDevices.getDisplayMedia({
          audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
          video: true,
        });
        if (display.getAudioTracks().length === 0) {
          display.getTracks().forEach((t) => t.stop());
          throw new Error("No tab audio — check 'Share tab audio' when prompted.");
        }
        display.getVideoTracks().forEach((t) => {
          t.stop();
          display.removeTrack(t);
        });
        acquired.push(display);
      }
      streams = acquired;
      ctx = new AudioContext();
      const dest = ctx.createMediaStreamDestination();
      for (const stream of acquired) {
        const node = ctx.createMediaStreamSource(stream);
        node.connect(dest);
        nodes.push(node);
      }
      const mixed = ctx.createMediaStreamSource(dest.stream);
      proc = ctx.createScriptProcessor(4096, 1, 1);
      proc.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
        const rms = Math.sqrt(sum / input.length);
        levelFill.style.width = Math.min(100, rms * 300) + "%";
        if (ws && ws.readyState === 1) ws.send(resampleTo16kPcm(input, ctx.sampleRate));
      };
      mixed.connect(proc);
      proc.connect(ctx.destination);
      return true;
    } catch (e) {
      acquired.forEach((s) => s.getTracks().forEach((t) => t.stop()));
      setStatus(e.message || String(e));
      return false;
    }
  }

  function stopCapture() {
    if (proc) proc.disconnect();
    nodes.forEach((n) => n.disconnect());
    nodes = [];
    streams.forEach((s) => s.getTracks().forEach((t) => t.stop()));
    streams = [];
    if (ctx) ctx.close();
    ctx = null;
    proc = null;
    levelFill.style.width = "0%";
  }

  function resampleTo16kPcm(input, srcRate) {
    const targetRate = 16000;
    let samples = input;
    if (srcRate !== targetRate) {
      const ratio = srcRate / targetRate;
      const newLen = Math.round(input.length / ratio);
      samples = new Float32Array(newLen);
      for (let i = 0; i < newLen; i++) {
        const srcIdx = i * ratio;
        const lo = Math.floor(srcIdx);
        const hi = Math.min(lo + 1, input.length - 1);
        const frac = srcIdx - lo;
        samples[i] = input[lo] * (1 - frac) + input[hi] * frac;
      }
    }
    const buf = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      buf[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return buf.buffer;
  }

  // ---- websocket --------------------------------------------------------
  function connect(resumeId, seriesId, title) {
    if (ws) return;
    intentionalClose = false;
    setStatus(resumeId ? "reconnecting…" : "loading models / connecting…");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    let params;
    if (resumeId) {
      params = `meeting_id=${resumeId}`;
    } else {
      params = `title=${encodeURIComponent(title || "Live session")}`;
      if (seriesId) params += `&series_id=${seriesId}`;
    }
    ws = new WebSocket(`${proto}://${location.host}/meetings/ws/?${params}`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => setStatus("live");
    ws.onmessage = (e) => {
      let msg;
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }
      if (msg.type === "ready") {
        meetingId = msg.meeting_id;
        retries = 0;
        setStatus("live · meeting #" + msg.meeting_id);
      } else if (msg.type === "partial") {
        renderPartial(msg.text);
      } else if (msg.type === "final") {
        clearPartial();
        appendFinal(msg);
      } else if (msg.type === "translation") {
        patchTranslation(msg.utterance_id, msg.translation);
      } else if (msg.type === "error") {
        setStatus("error: " + msg.message);
      }
    };
    ws.onerror = () => setStatus("connection error");
    ws.onclose = () => {
      ws = null;
      if (!intentionalClose && meetingId !== null && retries < 3) {
        retries += 1;
        setStatus(`连接中断 — 正在重连 (${retries}/3)…`);
        setTimeout(() => {
          if (!intentionalClose) {
            connect(meetingId);
          }
        }, 1500);
      } else if (!intentionalClose) {
        setStatus("connection closed");
      }
    };
  }

  // ---- transcript rendering ---------------------------------------------
  function renderPartial(text) {
    if (!partialEl) {
      partialEl = document.createElement("div");
      partialEl.className = "live-partial";
      transcriptEl.appendChild(partialEl);
    }
    partialEl.textContent = text;
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }

  function clearPartial() {
    if (partialEl) {
      partialEl.remove();
      partialEl = null;
    }
  }

  function appendFinal(msg) {
    const div = document.createElement("div");
    div.className = "live-final";
    div.dataset.utteranceId = msg.utterance_id;
    const text = document.createElement("span");
    text.className = "live-text";
    text.textContent = msg.text;
    div.appendChild(text);
    if (msg.translation) {
      const tr = document.createElement("blockquote");
      tr.className = "live-translation";
      tr.textContent = msg.translation;
      div.appendChild(tr);
    }
    transcriptEl.appendChild(div);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }

  function patchTranslation(utteranceId, translation) {
    const div = transcriptEl.querySelector(`[data-utterance-id="${utteranceId}"]`);
    if (!div) return;
    let tr = div.querySelector(".live-translation");
    if (!tr) {
      tr = document.createElement("blockquote");
      tr.className = "live-translation";
      div.appendChild(tr);
    }
    tr.textContent = translation;
  }

  function setStatus(text) {
    statusEl.textContent = text;
  }

  // ---- controls -----------------------------------------------------------
  startForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const title = startForm.title.value.trim() || "Live session";
    const seriesId = startForm.series_id.value || null;
    setup.hidden = true;
    run.hidden = false;
    connect(null, seriesId, title);
  });

  function activeSources() {
    const out = [];
    if (micBtn.classList.contains("on")) out.push("mic");
    if (sysBtn.classList.contains("on")) out.push("display");
    return out;
  }

  micBtn.addEventListener("click", async () => {
    micBtn.classList.toggle("on");
    micBtn.textContent = "Mic: " + (micBtn.classList.contains("on") ? "on" : "off");
    const sources = activeSources();
    if (sources.length) await startCapture(sources);
    else stopCapture();
  });

  sysBtn.addEventListener("click", async () => {
    sysBtn.classList.toggle("on");
    sysBtn.textContent = "System audio: " + (sysBtn.classList.contains("on") ? "on" : "off");
    const sources = activeSources();
    if (sources.length) await startCapture(sources);
    else stopCapture();
  });

  translateBtn.addEventListener("click", () => {
    translateOn = !translateOn;
    translateBtn.classList.toggle("on", translateOn);
    translateBtn.setAttribute("aria-pressed", translateOn);
    translateBtn.textContent = "译 " + (translateOn ? "on" : "off");
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({ type: "translate", enabled: translateOn }));
    }
  });

  stopBtn.addEventListener("click", () => {
    intentionalClose = true;
    stopCapture();
    if (ws) ws.close();
    setStatus("saving audio…");
    // Give the server a moment to flush + write the WAV, then open the meeting.
    setTimeout(() => {
      window.location = meetingId ? `/meetings/${meetingId}/` : "/meetings/";
    }, 1200);
  });
})();
