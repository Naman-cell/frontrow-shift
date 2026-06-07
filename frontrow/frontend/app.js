const els = {
  apiBase: document.querySelector("#apiBase"),
  wsBase: document.querySelector("#wsBase"),
  voiceEnabled: document.querySelector("#voiceEnabled"),
  candidateId: document.querySelector("#candidateId"),
  roleTitle: document.querySelector("#roleTitle"),
  rolePreset: document.querySelector("#rolePreset"),
  durationMinutes: document.querySelector("#durationMinutes"),
  requiredSkills: document.querySelector("#requiredSkills"),
  jobSummary: document.querySelector("#jobSummary"),
  resumeSummary: document.querySelector("#resumeSummary"),
  interviewId: document.querySelector("#interviewId"),
  status: document.querySelector("#status"),
  metaLine: document.querySelector("#metaLine"),
  latencySummary: document.querySelector("#latencySummary"),
  latencyOutput: document.querySelector("#latencyOutput"),
  messages: document.querySelector("#messages"),
  answerText: document.querySelector("#answerText"),
  reportOutput: document.querySelector("#reportOutput"),
  createBtn: document.querySelector("#createBtn"),
  connectBtn: document.querySelector("#connectBtn"),
  completeBtn: document.querySelector("#completeBtn"),
  reportBtn: document.querySelector("#reportBtn"),
  sendBtn: document.querySelector("#sendBtn"),
  recordBtn: document.querySelector("#recordBtn"),
  stopRecordBtn: document.querySelector("#stopRecordBtn"),
  clearBtn: document.querySelector("#clearBtn"),
  dontKnowBtn: document.querySelector("#dontKnowBtn"),
  strongBtn: document.querySelector("#strongBtn"),
  answerForm: document.querySelector("#answerForm"),
  recordingStatus: document.querySelector("#recordingStatus"),
  answerPreview: document.querySelector("#answerPreview"),
};

let socket = null;
let mediaRecorder = null;
let recordedChunks = [];
let recordedBlob = null;
let sendRecordingOnStop = false;
let currentAudioStreamId = null;
let audioChunkUploads = [];
let audioContext = null;
let silenceMonitor = null;
let countdownInterval = null;
let interviewEndsAt = null;
let voiceSocket = null;
let voiceReadyPromise = null;
let voiceReadyResolve = null;
let voiceReadyReject = null;
let streamingVoicePlayer = null;
let activeVoiceBlock = null;
let pendingCandidateMessage = null;
let voiceDoneResolve = null;
let voiceDoneReject = null;
let activeLatencyTrace = null;
let latencySequence = 0;
const latencyTraces = [];

const rolePresets = {
  software: {
    roleTitle: "Python Backend Engineer",
    skills: [
      "Python concurrency",
      "FastAPI",
      "API design",
      "PostgreSQL",
      "Redis",
      "Production debugging",
      "AI model integration",
    ],
    jobSummary:
      "We need a backend engineer who can build FastAPI services, design REST APIs, work with PostgreSQL and Redis, debug production issues, and integrate AI model APIs.",
    resumeSummary:
      "Candidate has 3 years of backend experience with Python, FastAPI, PostgreSQL, Redis, Docker, and claims to have worked on AI model deployment.",
    strongSample:
      "For example, I designed a FastAPI service where Redis cached expensive reads and PostgreSQL handled durable writes. The tradeoff was cache invalidation, so we measured latency, stale reads, and error rates in production.",
  },
  nurse: {
    roleTitle: "Emergency Room Nurse",
    skills: [
      "Patient triage",
      "Medication safety",
      "Clinical communication",
      "Emergency prioritization",
      "Patient handoff",
    ],
    jobSummary:
      "We need an emergency room nurse who can triage patients, follow medication safety practices, communicate clearly under pressure, and coordinate handoffs.",
    resumeSummary:
      "Candidate has clinical rotation experience, patient triage exposure, and claims to have handled fast-paced emergency department situations.",
    strongSample:
      "For example, during a clinical rotation I helped triage a patient with shortness of breath by escalating symptoms quickly, communicating vitals clearly, and staying with the patient until the nurse took over.",
  },
  forklift: {
    roleTitle: "Warehouse Forklift Operator",
    skills: [
      "Forklift safety",
      "Inventory handling",
      "Site procedures",
      "Shift communication",
      "Equipment checks",
    ],
    jobSummary:
      "We need a warehouse operator who can move inventory safely, follow site procedures, inspect equipment, and communicate clearly during shifts.",
    resumeSummary:
      "Candidate has warehouse shift experience, basic equipment handling, and claims to have supported loading, unloading, and inventory movement.",
    strongSample:
      "For example, before moving pallets I checked the forklift, confirmed the route was clear, followed the load limit, and told the shift lead when an aisle was blocked.",
  },
  sales: {
    roleTitle: "Retail Sales Associate",
    skills: [
      "Customer discovery",
      "Product explanation",
      "Objection handling",
      "Checkout accuracy",
      "Team communication",
    ],
    jobSummary:
      "We need a retail sales associate who can understand customer needs, explain products clearly, handle objections, and support store operations.",
    resumeSummary:
      "Candidate has customer-facing retail experience and claims to have helped customers choose products and resolve service issues.",
    strongSample:
      "For example, I once asked a customer what they needed the item for, compared two options in stock, explained the tradeoff, and helped them choose the better fit.",
  },
};

function setStatus(value) {
  els.status.textContent = value;
}

function setChatEnabled(enabled) {
  els.answerText.disabled = !enabled;
  els.sendBtn.disabled = !enabled;
  els.recordBtn.disabled = !enabled;
  els.dontKnowBtn.disabled = !enabled;
  els.strongBtn.disabled = !enabled;
  if (!enabled) els.stopRecordBtn.disabled = true;
}

function applyRolePreset(name) {
  const preset = rolePresets[name];
  if (!preset) return;
  els.roleTitle.value = preset.roleTitle;
  els.requiredSkills.value = preset.skills.join("\n");
  els.jobSummary.value = preset.jobSummary;
  els.resumeSummary.value = preset.resumeSummary;
}

function startCountdown(totalSeconds) {
  const seconds = Number(totalSeconds);
  if (!Number.isFinite(seconds) || seconds <= 0) return;
  interviewEndsAt = Date.now() + seconds * 1000;
  renderCountdown();
  clearInterval(countdownInterval);
  countdownInterval = setInterval(renderCountdown, 1000);
}

function stopCountdown() {
  clearInterval(countdownInterval);
  countdownInterval = null;
  interviewEndsAt = null;
}

function renderCountdown() {
  if (!interviewEndsAt) return;
  const remaining = Math.max(0, Math.ceil((interviewEndsAt - Date.now()) / 1000));
  const minutes = Math.floor(remaining / 60);
  const seconds = String(remaining % 60).padStart(2, "0");
  els.metaLine.textContent = `Time left: ${minutes}:${seconds}`;
  if (remaining <= 0) {
    clearInterval(countdownInterval);
    countdownInterval = null;
  }
}

function addMessage(kind, text, meta = null) {
  const div = document.createElement("div");
  div.className = `message ${kind}`;
  const label = kind === "candidate" ? "Candidate" : kind === "system" ? "System" : "Interviewer";
  div.innerHTML = `
    <div class="label">${label}</div>
    <div>${escapeHtml(text || "")}</div>
    ${meta ? `<div class="meta">${escapeHtml(formatMeta(meta))}</div>` : ""}
  `;
  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
  return div;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatMeta(meta) {
  const parts = [];
  if (meta.move_type) parts.push(`move: ${meta.move_type}`);
  if (meta.target_skill) parts.push(`skill: ${meta.target_skill}`);
  if (meta.reason) parts.push(`reason: ${meta.reason}`);
  return parts.join(" | ");
}

function apiUrl(path) {
  return `${els.apiBase.value.replace(/\/$/, "")}${path}`;
}

function wsUrl(path) {
  return `${els.wsBase.value.replace(/\/$/, "")}${path}`;
}

function demoPayload() {
  const requiredSkills = els.requiredSkills.value
    .split("\n")
    .map((skill) => skill.trim())
    .filter(Boolean);
  const roleTitle = els.roleTitle.value || "Python Backend Engineer";

  return {
    tenant_id: "org_demo",
    candidate_id: els.candidateId.value || "candidate_001",
    role: {
      role_id: roleTitle.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""),
      title: roleTitle,
      seniority: "mid",
      job_description_summary: els.jobSummary.value,
      resume_summary: els.resumeSummary.value,
      resume_claims: [els.resumeSummary.value].filter(Boolean),
      required_skills: requiredSkills,
    },
    duration_minutes: Number(els.durationMinutes.value || 20),
    question_mode: "AI",
    planned_questions: [],
  };
}

async function createAndStart() {
  setStatus("creating");
  const createRes = await fetch(apiUrl("/interviews"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(demoPayload()),
  });
  if (!createRes.ok) throw new Error(await createRes.text());
  const session = await createRes.json();
  els.interviewId.value = session.interview_id;

  setStatus("starting");
  const startRes = await fetch(apiUrl(`/interviews/${session.interview_id}/start`), {
    method: "POST",
  });
  if (!startRes.ok) throw new Error(await startRes.text());
  await startRes.json();
  els.connectBtn.disabled = false;
  els.completeBtn.disabled = false;
  els.reportBtn.disabled = false;
  els.metaLine.textContent = `Interview ${session.interview_id}`;
  setStatus("started");
  connectSocket();
}

function connectSocket() {
  const interviewId = els.interviewId.value.trim();
  if (!interviewId) {
    addMessage("system", "Create/start an interview first.");
    return;
  }
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }

  setStatus("connecting");
  socket = new WebSocket(wsUrl(`/interviews/${interviewId}/ws`));

  socket.addEventListener("open", () => {
    setStatus("connected");
    setChatEnabled(true);
    addMessage("system", "WebSocket connected.");
    ensureVoiceSocket().catch((err) => addMessage("system", err.message));
  });

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.error) {
      addMessage("system", `${payload.error}: ${JSON.stringify(payload.details || {})}`);
      return;
    }
    markBackendResponse(payload.meta || {});
    updatePendingCandidateMessage(payload.meta || {});
    const voiceDone = payload.query_asked || payload.reconnect
      ? addInterviewerPayload(payload)
      : Promise.resolve();
    if (payload.completed) {
      setStatus("wrapping up");
      setChatEnabled(false);
      stopCountdown();
      voiceDone.finally(() => {
        setStatus("completed");
        addMessage("system", "Interview completed. Fetch report when ready.");
      });
    }
  });

  socket.addEventListener("close", () => {
    if (els.status.textContent !== "completed") setStatus("disconnected");
    setChatEnabled(false);
  });

  socket.addEventListener("error", () => {
    setStatus("socket error");
    addMessage("system", "WebSocket error. Check API server logs.");
  });
}

function addInterviewerPayload(payload) {
  const question = payload.query_asked || payload.reconnect?.current_question || "";
  const meta = payload.meta || {};
  let voiceDone = Promise.resolve();
  if (question) {
    if (!activeLatencyTrace) {
      startLatencyTrace("opening", { audioKb: 0 });
      markBackendResponse(meta);
    }
    markLatency("questionDisplayedAt");
    const message = addMessage("interviewer", question, meta);
    voiceDone = streamAzureVoice(question, message).catch((err) => {
      addMessage("system", err.message);
    });
  }
  startCountdown(payload.reconnect?.remaining_seconds || payload.interview_duration);
  return voiceDone;
}

async function streamAzureVoice(text, message) {
  if (!els.voiceEnabled?.checked || !text) return;

  const audioBlock = document.createElement("div");
  audioBlock.className = "audio-block";
  audioBlock.innerHTML = `
    <div class="audio-label">Azure voice</div>
    <div class="voice-wait">Opening voice stream...</div>
  `;
  message.appendChild(audioBlock);
  activeVoiceBlock = audioBlock;
  await ensureVoiceSocket();
  ensureStreamingPlayer().reset();
  updateVoiceBlock("Streaming voice...");
  markLatency("voiceRequestedAt");
  if (voiceDoneResolve) {
    voiceDoneResolve();
    voiceDoneResolve = null;
    voiceDoneReject = null;
  }
  const done = new Promise((resolve, reject) => {
    voiceDoneResolve = resolve;
    voiceDoneReject = reject;
  });
  voiceSocket.send(JSON.stringify({ text }));
  return done;
}

function ensureVoiceSocket() {
  if (!els.voiceEnabled?.checked) return Promise.resolve();
  if (voiceSocket && voiceSocket.readyState === WebSocket.OPEN) return Promise.resolve();
  if (voiceReadyPromise) return voiceReadyPromise;

  voiceReadyPromise = new Promise((resolve, reject) => {
    voiceReadyResolve = resolve;
    voiceReadyReject = reject;
    voiceSocket = new WebSocket(wsUrl("/voice/live"));
    voiceSocket.binaryType = "arraybuffer";

    voiceSocket.addEventListener("message", (event) => {
      if (event.data instanceof ArrayBuffer) {
        ensureStreamingPlayer().push(event.data);
        return;
      }
      let payload = {};
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      handleVoiceControlMessage(payload);
    });

    voiceSocket.addEventListener("open", () => {
      updateVoiceBlock("Voice stream connected.");
    });

    voiceSocket.addEventListener("close", () => {
      if (voiceReadyReject) {
        voiceReadyReject(new Error("Azure voice socket closed before it was ready."));
      }
      voiceSocket = null;
      voiceReadyPromise = null;
      voiceReadyResolve = null;
      voiceReadyReject = null;
    });

    voiceSocket.addEventListener("error", () => {
      voiceReadyPromise = null;
      voiceReadyResolve = null;
      voiceReadyReject = null;
      reject(new Error("Azure voice socket error."));
    });
  });

  return voiceReadyPromise;
}

function handleVoiceControlMessage(payload) {
  if (payload.type === "ready") {
    ensureStreamingPlayer(payload.sample_rate || 24000);
    updateVoiceBlock("Voice stream ready.");
    if (voiceReadyResolve) voiceReadyResolve();
    voiceReadyResolve = null;
    voiceReadyReject = null;
    return;
  }
  if (payload.type === "voice_start") {
    ensureStreamingPlayer(payload.sample_rate || 24000).reset();
    markLatency("voiceStartAt");
    updateVoiceBlock("Speaking...");
    return;
  }
  if (payload.type === "voice_end") {
    markLatency("voiceEndAt");
    updateVoiceBlock("Voice stream complete.");
    if (voiceDoneResolve) {
      voiceDoneResolve();
      voiceDoneResolve = null;
      voiceDoneReject = null;
    }
    completeLatencyTrace();
    return;
  }
  if (payload.type === "voice_cancelled") {
    updateVoiceBlock("Voice stream interrupted.");
    if (voiceDoneResolve) {
      voiceDoneResolve();
      voiceDoneResolve = null;
      voiceDoneReject = null;
    }
    return;
  }
  if (payload.type === "error") {
    const message = payload.message || "Azure voice failed.";
    updateVoiceBlock(message);
    if (voiceDoneReject) {
      voiceDoneReject(new Error(message));
      voiceDoneResolve = null;
      voiceDoneReject = null;
    }
    if (voiceReadyReject) {
      voiceReadyReject(new Error(message));
      voiceReadyReject = null;
      voiceReadyResolve = null;
    } else {
      addMessage("system", message);
    }
  }
}

function updateVoiceBlock(text) {
  if (!activeVoiceBlock) return;
  activeVoiceBlock.innerHTML = `
    <div class="audio-label">Azure voice</div>
    <div class="voice-wait">${escapeHtml(text)}</div>
  `;
}

function ensureStreamingPlayer(sampleRate = 24000) {
  if (!streamingVoicePlayer || streamingVoicePlayer.sampleRate !== sampleRate) {
    streamingVoicePlayer = new PcmStreamPlayer(sampleRate);
  }
  streamingVoicePlayer.resume().catch(() => {});
  return streamingVoicePlayer;
}

class PcmStreamPlayer {
  constructor(sampleRate) {
    this.sampleRate = sampleRate;
    this.audioContext = null;
    this.nextStartTime = 0;
    this.sources = [];
    this.pendingByte = null;
  }

  async resume() {
    if (!this.audioContext) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioContextClass({ sampleRate: this.sampleRate });
      this.nextStartTime = this.audioContext.currentTime;
    }
    if (this.audioContext.state === "suspended") {
      await this.audioContext.resume();
    }
  }

  reset() {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // Already stopped.
      }
    }
    this.sources = [];
    this.pendingByte = null;
    if (this.audioContext) {
      this.nextStartTime = this.audioContext.currentTime;
    }
  }

  push(arrayBuffer) {
    if (!this.audioContext) return;
    markFirstAudioByte();
    let bytes = new Uint8Array(arrayBuffer);
    if (this.pendingByte !== null) {
      const merged = new Uint8Array(bytes.length + 1);
      merged[0] = this.pendingByte;
      merged.set(bytes, 1);
      bytes = merged;
      this.pendingByte = null;
    }
    if (bytes.length % 2 === 1) {
      this.pendingByte = bytes[bytes.length - 1];
      bytes = bytes.slice(0, -1);
    }
    if (bytes.length === 0) return;

    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const samples = new Float32Array(bytes.length / 2);
    for (let i = 0; i < samples.length; i += 1) {
      samples[i] = view.getInt16(i * 2, true) / 32768;
    }
    const buffer = this.audioContext.createBuffer(1, samples.length, this.sampleRate);
    buffer.getChannelData(0).set(samples);
    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audioContext.destination);
    const now = this.audioContext.currentTime;
    if (this.nextStartTime < now) this.nextStartTime = now;
    source.start(this.nextStartTime);
    this.nextStartTime += buffer.duration;
    this.sources.push(source);
    source.addEventListener("ended", () => {
      this.sources = this.sources.filter((item) => item !== source);
    });
  }
}

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function sendAnswer(text, flags = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    addMessage("system", "WebSocket is not connected.");
    return;
  }
  let audioBase64 = null;
  let audioMimeType = null;
  if (currentAudioStreamId && audioChunkUploads.length) {
    await Promise.allSettled(audioChunkUploads);
    audioMimeType = recordedBlob?.type || mediaRecorder?.mimeType || "audio/webm";
  } else if (recordedBlob) {
    audioBase64 = await blobToBase64(recordedBlob);
    audioMimeType = recordedBlob.type || "audio/webm";
  }
  const payload = {
    message_type: "answer",
    text,
    audio_ref: null,
    audio_stream_id: currentAudioStreamId,
    audio_base64: audioBase64,
    audio_mime_type: audioMimeType,
    user_leave: false,
    overtime: false,
    is_complete: false,
    ...flags,
  };
  const audioKb = recordedBlob ? Math.round(recordedBlob.size / 1024) : 0;
  startLatencyTrace(recordedBlob ? "audio" : "text", { audioKb });
  socket.send(JSON.stringify(payload));
  if (recordedBlob) {
    pendingCandidateMessage = addMessage("candidate", text || "[audio answer submitted]", {
      move_type: "audio",
      reason: `${Math.round(recordedBlob.size / 1024)} KB ${audioMimeType}`,
    });
  } else if (text) {
    pendingCandidateMessage = addMessage("candidate", text);
  }
  resetRecording();
  els.answerText.value = "";
}

function startLatencyTrace(trigger, extra = {}) {
  activeLatencyTrace = {
    id: ++latencySequence,
    trigger,
    startedAt: performance.now(),
    wallClock: new Date().toLocaleTimeString(),
    audioKb: extra.audioKb || 0,
    answerSentAt: performance.now(),
    backendResponseAt: null,
    questionDisplayedAt: null,
    voiceRequestedAt: null,
    voiceStartAt: null,
    firstAudioByteAt: null,
    voiceEndAt: null,
    backendTurnMs: null,
    backendDetail: "",
    status: "waiting",
  };
  latencyTraces.unshift(activeLatencyTrace);
  if (latencyTraces.length > 12) latencyTraces.pop();
  renderLatency();
}

function markLatency(field) {
  if (!activeLatencyTrace || activeLatencyTrace[field]) return;
  activeLatencyTrace[field] = performance.now();
  renderLatency();
}

function markBackendResponse(meta) {
  if (!activeLatencyTrace) return;
  markLatency("backendResponseAt");
  const latency = meta?.latency_ms || {};
  const backendTotal = latency.backend_total;
  const turnPipeline = latency.turn_pipeline;
  const displayedBackend = Number.isFinite(Number(backendTotal)) ? backendTotal : turnPipeline;
  if (Number.isFinite(Number(displayedBackend))) {
    activeLatencyTrace.backendTurnMs = Number(displayedBackend);
  }
  activeLatencyTrace.backendDetail = formatBackendLatencyDetail(latency);
  renderLatency();
}

function markFirstAudioByte() {
  if (!activeLatencyTrace || activeLatencyTrace.firstAudioByteAt) return;
  activeLatencyTrace.firstAudioByteAt = performance.now();
  renderLatency();
}

function completeLatencyTrace() {
  if (!activeLatencyTrace) return;
  activeLatencyTrace.status = "done";
  renderLatency();
  activeLatencyTrace = null;
}

function msSince(trace, field) {
  if (!trace?.[field]) return "—";
  return `${Math.max(0, Math.round(trace[field] - trace.answerSentAt))} ms`;
}

function msBetween(trace, startField, endField) {
  if (!trace?.[startField] || !trace?.[endField]) return "—";
  return `${Math.max(0, Math.round(trace[endField] - trace[startField]))} ms`;
}

function renderLatency() {
  if (!els.latencyOutput) return;
  const latest = latencyTraces[0];
  if (latest) {
    const total = latest.voiceEndAt
      ? msSince(latest, "voiceEndAt")
      : latest.firstAudioByteAt
        ? `${msSince(latest, "firstAudioByteAt")} to first audio`
        : latest.backendResponseAt
          ? `${msSince(latest, "backendResponseAt")} to text`
          : "waiting";
    els.latencySummary.textContent = `Turn ${latest.id}: ${total}`;
  }
  els.latencyOutput.innerHTML = latencyTraces
    .map((trace) => `
      <div class="latency-row">
        ${latencyCell(`#${trace.id}`, `${trace.trigger}${trace.audioKb ? ` · ${trace.audioKb} KB` : ""}`)}
        ${latencyCell("Backend", trace.backendTurnMs ? `${trace.backendTurnMs} ms` : msSince(trace, "backendResponseAt"), trace.backendDetail)}
        ${latencyCell("Text shown", msSince(trace, "questionDisplayedAt"))}
        ${latencyCell("TTS start", msSince(trace, "voiceStartAt"))}
        ${latencyCell("1st audio", msSince(trace, "firstAudioByteAt"))}
        ${latencyCell("Speak total", msBetween(trace, "voiceStartAt", "voiceEndAt"))}
      </div>
    `)
    .join("");
}

function latencyCell(label, value, detail = "") {
  return `
    <div class="latency-cell">
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(label)}</span>
      ${detail ? `<small>${escapeHtml(detail)}</small>` : ""}
    </div>
  `;
}

function formatBackendLatencyDetail(latency) {
  const parts = [];
  const add = (label, key) => {
    const value = latency?.[key];
    if (Number.isFinite(Number(value))) parts.push(`${label} ${Math.round(Number(value))}`);
  };
  add("haystack", "turn_pipeline");
  add("audio", "answer_understanding_ms");
  add("question", "question_generator_ms");
  add("save", "state_save");
  return parts.length ? `${parts.join(" · ")} ms` : "";
}

function updatePendingCandidateMessage(meta) {
  if (!pendingCandidateMessage) return;
  const transcript = meta.candidate_transcript || "";
  const summary = meta.candidate_answer_summary || "";
  const displayText = transcript || summary;
  if (!displayText) return;
  pendingCandidateMessage.innerHTML = `
    <div class="label">Candidate</div>
    <div>${escapeHtml(displayText)}</div>
    <div class="meta">${escapeHtml(formatMeta({
      move_type: "analyzed_audio",
      reason: transcript ? "Gemini transcript" : "Gemini answer summary",
    }))}</div>
  `;
  pendingCandidateMessage = null;
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    addMessage("system", "Microphone recording is not available in this browser.");
    return;
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recordedChunks = [];
  recordedBlob = null;
  currentAudioStreamId = crypto.randomUUID();
  audioChunkUploads = [];
  const options = MediaRecorder.isTypeSupported("audio/webm")
    ? { mimeType: "audio/webm" }
    : undefined;
  mediaRecorder = new MediaRecorder(stream, options);
  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) {
      recordedChunks.push(event.data);
      audioChunkUploads.push(sendAudioChunk(event.data, currentAudioStreamId));
    }
  });
  mediaRecorder.addEventListener("stop", () => {
    recordedBlob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || "audio/webm" });
    els.answerPreview.src = URL.createObjectURL(recordedBlob);
    els.recordingStatus.textContent = `Recorded ${Math.round(recordedBlob.size / 1024)} KB`;
    stream.getTracks().forEach((track) => track.stop());
    stopSilenceMonitor();
    els.recordBtn.disabled = false;
    els.stopRecordBtn.disabled = true;
    if (sendRecordingOnStop) {
      sendRecordingOnStop = false;
      els.recordingStatus.textContent = "Sending recorded answer to Gemini...";
      sendAnswer(els.answerText.value.trim()).catch((err) => addMessage("system", err.message));
    }
  });
  mediaRecorder.start(250);
  monitorSilence(stream);
  sendRecordingOnStop = true;
  els.recordingStatus.textContent = "Listening...";
  els.recordBtn.disabled = true;
  els.stopRecordBtn.disabled = false;
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    sendRecordingOnStop = true;
    mediaRecorder.stop();
  }
}

function resetRecording() {
  recordedChunks = [];
  recordedBlob = null;
  currentAudioStreamId = null;
  audioChunkUploads = [];
  sendRecordingOnStop = false;
  stopSilenceMonitor();
  els.answerPreview.removeAttribute("src");
  els.recordingStatus.textContent = "No recording";
}

async function sendAudioChunk(blob, streamId) {
  if (!streamId || !socket || socket.readyState !== WebSocket.OPEN) return;
  const chunkBase64 = await blobToBase64(blob);
  socket.send(JSON.stringify({
    message_type: "audio_chunk",
    audio_stream_id: streamId,
    audio_chunk_base64: chunkBase64,
    audio_mime_type: blob.type || mediaRecorder?.mimeType || "audio/webm",
  }));
}

function monitorSilence(stream) {
  stopSilenceMonitor();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  audioContext = new AudioContextClass();
  const source = audioContext.createMediaStreamSource(stream);
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const data = new Uint8Array(analyser.fftSize);
  const startedAt = Date.now();
  let quietSince = null;

  function tick() {
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const value of data) {
      const normalized = (value - 128) / 128;
      sum += normalized * normalized;
    }
    const rms = Math.sqrt(sum / data.length);
    const now = Date.now();
    if (rms < 0.018) {
      quietSince = quietSince || now;
    } else {
      quietSince = null;
    }
    if (quietSince && now - quietSince > 1500 && now - startedAt > 1800) {
      stopRecording();
      return;
    }
    silenceMonitor = requestAnimationFrame(tick);
  }
  tick();
}

function stopSilenceMonitor() {
  if (silenceMonitor) {
    cancelAnimationFrame(silenceMonitor);
    silenceMonitor = null;
  }
  if (audioContext) {
    audioContext.close().catch(() => {});
    audioContext = null;
  }
}

async function completeInterview() {
  const interviewId = els.interviewId.value.trim();
  if (!interviewId) return;
  setStatus("completing");
  const res = await fetch(apiUrl(`/interviews/${interviewId}/complete`), {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  renderReport(await res.json());
  setStatus("completed");
}

async function fetchReport() {
  const interviewId = els.interviewId.value.trim();
  if (!interviewId) return;
  const res = await fetch(apiUrl(`/interviews/${interviewId}/report`));
  if (!res.ok) throw new Error(await res.text());
  renderReport(await res.json());
}

function renderReport(report) {
  const composition = report.score_composition || [];
  const skills = report.skill_role_match || [];
  const worries = report.worry_areas || [];
  const steps = report.recommended_next_steps || [];
  const evidence = report.evidence_by_question || [];
  els.reportOutput.innerHTML = `
    <div class="report-score">
      <strong>${escapeHtml(report.fit_score ?? Math.round((report.overall_score || 0) * 100))}</strong>
      <span>${escapeHtml(report.verdict || report.recommendation || "needs_review")} · role bar ${escapeHtml(report.role_bar || 70)}</span>
      <p>${escapeHtml(report.rationale || "")}</p>
    </div>
    ${reportSection("Score Composition", composition.map((item) =>
      reportItem(item.label, `${item.score_4}/4 · ${Math.round(item.weight * 100)}% · ${item.points} pts`, item.rationale)
    ).join(""))}
    ${reportSection("Skill To Role", skills.map((item) =>
      reportItem(item.label, item.assessed ? `${item.candidate_level_4}/4 · ${item.band}` : "Not assessed", `Target ${item.required_level_4}/4`)
    ).join(""))}
    ${reportSection("Where To Worry", worries.map((item) =>
      reportItem(item.title, item.summary, `Evidence: ${(item.evidence_ids || []).join(", ") || "none"}`)
    ).join(""))}
    ${reportSection("Recommended Next Steps", steps.map((item) =>
      reportItem(item.title, item.summary, "")
    ).join(""))}
    ${reportSection("Evidence By Question", evidence.map((item) =>
      reportItem(`Q${item.turn_index}: ${item.skill_id}`, item.question, `${item.score_4}/4 · ${item.ai_judgement}`)
    ).join(""))}
  `;
}

function reportSection(title, body) {
  if (!body) return "";
  return `<div class="report-section"><h3>${escapeHtml(title)}</h3>${body}</div>`;
}

function reportItem(title, line, detail) {
  return `
    <div class="report-item">
      <b>${escapeHtml(title || "")}</b>
      <div>${escapeHtml(line || "")}</div>
      ${detail ? `<small>${escapeHtml(detail)}</small>` : ""}
    </div>
  `;
}

els.createBtn.addEventListener("click", () => {
  createAndStart().catch((err) => {
    setStatus("error");
    addMessage("system", err.message);
  });
});

els.connectBtn.addEventListener("click", connectSocket);
els.rolePreset.addEventListener("change", () => applyRolePreset(els.rolePreset.value));
els.completeBtn.addEventListener("click", () => completeInterview().catch((err) => addMessage("system", err.message)));
els.reportBtn.addEventListener("click", () => fetchReport().catch((err) => addMessage("system", err.message)));
els.clearBtn.addEventListener("click", () => {
  els.messages.innerHTML = "";
});

els.answerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = els.answerText.value.trim();
  if (text || recordedBlob) sendAnswer(text).catch((err) => addMessage("system", err.message));
});

els.dontKnowBtn.addEventListener("click", () => {
  sendAnswer("I am not sure, I do not know that topic well.");
});

els.strongBtn.addEventListener("click", () => {
  const preset = rolePresets[els.rolePreset.value] || rolePresets.software;
  sendAnswer(preset.strongSample);
});

els.recordBtn.addEventListener("click", () => {
  startRecording().catch((err) => addMessage("system", err.message));
});

els.stopRecordBtn.addEventListener("click", stopRecording);
