const els = {
  apiBase: document.querySelector("#apiBase"),
  wsBase: document.querySelector("#wsBase"),
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
let activeInterviewerAudio = null;
let sendRecordingOnStop = false;
let lastInterviewerMessage = null;
let audioContext = null;
let silenceMonitor = null;
let countdownInterval = null;
let interviewEndsAt = null;

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

function addMessage(kind, text, meta = null, audio = null) {
  const div = document.createElement("div");
  div.className = `message ${kind}`;
  const label = kind === "candidate" ? "Candidate" : kind === "system" ? "System" : "Interviewer";
  const audioMarkup = audio
    ? `
      <div class="audio-block">
        <div class="audio-label">Google Gemini voice</div>
        <audio class="model-audio" controls preload="auto" src="${audio.url}"></audio>
      </div>
    `
    : "";
  div.innerHTML = `
    <div class="label">${label}</div>
    <div>${escapeHtml(text || "")}</div>
    ${audioMarkup}
    ${meta ? `<div class="meta">${escapeHtml(formatMeta(meta))}</div>` : ""}
  `;
  els.messages.appendChild(div);
  if (kind === "interviewer") {
    lastInterviewerMessage = div;
  }
  els.messages.scrollTop = els.messages.scrollHeight;
  if (audio?.autoplay) {
    const audioEl = div.querySelector("audio");
    if (activeInterviewerAudio && activeInterviewerAudio !== audioEl) {
      activeInterviewerAudio.pause();
    }
    activeInterviewerAudio = audioEl;
    audioEl?.play().catch(() => {
      addMessage("system", "Google voice is ready. Press play on the audio control if autoplay was blocked.");
    });
  }
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
  if (meta.tts) parts.push(`voice: ${meta.tts}`);
  if (meta.move_type) parts.push(`move: ${meta.move_type}`);
  if (meta.target_skill) parts.push(`skill: ${meta.target_skill}`);
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
  });

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.error) {
      addMessage("system", `${payload.error}: ${JSON.stringify(payload.details || {})}`);
      return;
    }
    if (payload.message_type === "audio") {
      attachAudioPayload(payload);
      return;
    }
    if (payload.query_asked || payload.reconnect) {
      addInterviewerPayload(payload);
    }
    if (payload.completed) {
      setStatus("completed");
      setChatEnabled(false);
      stopCountdown();
      addMessage("system", "Interview completed. Fetch report when ready.");
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
  const audio = payload.audio_base64
    ? {
        url: audioUrlFromBase64(
          payload.audio_base64,
          payload.audio_mime_type || "audio/wav"
        ),
        autoplay: true,
      }
    : null;
  const message = question ? addMessage("interviewer", question, meta, audio) : null;
  if (message && !audio) {
    addAudioLoading(message);
  }
  if (meta.tts_error) {
    addMessage("system", `Google Gemini TTS failed: ${meta.tts_error}`);
  }
  startCountdown(payload.reconnect?.remaining_seconds || payload.interview_duration);
}

function addAudioLoading(message) {
  const div = document.createElement("div");
  div.className = "audio-block audio-loading";
  div.innerHTML = `
    <div class="audio-label">Google Gemini voice</div>
    <div class="voice-wait">Preparing voice...</div>
  `;
  message.appendChild(div);
}

function attachAudioPayload(payload) {
  if (payload.meta?.tts_error) {
    const existing = lastInterviewerMessage?.querySelector(".audio-block");
    existing?.remove();
    addMessage("system", `Google Gemini TTS failed: ${payload.meta.tts_error}`);
    return;
  }
  if (!payload.audio_base64 || !lastInterviewerMessage) return;
  const existing = lastInterviewerMessage.querySelector(".audio-block");
  existing?.remove();
  const audioUrl = audioUrlFromBase64(payload.audio_base64, payload.audio_mime_type || "audio/wav");
  const wrapper = document.createElement("div");
  wrapper.className = "audio-block";
  wrapper.innerHTML = `
    <div class="audio-label">Google Gemini voice</div>
    <audio class="model-audio" controls preload="auto" src="${audioUrl}"></audio>
  `;
  lastInterviewerMessage.appendChild(wrapper);
  const audioEl = wrapper.querySelector("audio");
  if (activeInterviewerAudio && activeInterviewerAudio !== audioEl) {
    activeInterviewerAudio.pause();
  }
  activeInterviewerAudio = audioEl;
  audioEl?.play().catch(() => {});
}

function audioUrlFromBase64(base64, mimeType) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: mimeType });
  return URL.createObjectURL(blob);
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
  if (recordedBlob) {
    audioBase64 = await blobToBase64(recordedBlob);
    audioMimeType = recordedBlob.type || "audio/webm";
  }
  const payload = {
    text,
    audio_ref: null,
    audio_base64: audioBase64,
    audio_mime_type: audioMimeType,
    user_leave: false,
    overtime: false,
    is_complete: false,
    ...flags,
  };
  socket.send(JSON.stringify(payload));
  if (recordedBlob) {
    addMessage("candidate", text || "[audio answer submitted]", {
      move_type: "audio",
      reason: `${Math.round(recordedBlob.size / 1024)} KB ${audioMimeType}`,
    });
  } else if (text) {
    addMessage("candidate", text);
  }
  resetRecording();
  els.answerText.value = "";
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    addMessage("system", "Microphone recording is not available in this browser.");
    return;
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recordedChunks = [];
  recordedBlob = null;
  const options = MediaRecorder.isTypeSupported("audio/webm")
    ? { mimeType: "audio/webm" }
    : undefined;
  mediaRecorder = new MediaRecorder(stream, options);
  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) recordedChunks.push(event.data);
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
  sendRecordingOnStop = false;
  stopSilenceMonitor();
  els.answerPreview.removeAttribute("src");
  els.recordingStatus.textContent = "No recording";
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
