const textEl = document.getElementById("text");
const countEl = document.getElementById("count");
const presetEl = document.getElementById("preset");
const presetMetaEl = document.getElementById("preset-meta");
const metaCategoryEl = document.getElementById("meta-category");
const metaExpectedEl = document.getElementById("meta-expected");
const metaWindowEl = document.getElementById("meta-window");
const metaRecordingEl = document.getElementById("meta-recording");
const metaNotesEl = document.getElementById("meta-notes");
const voiceEl = document.getElementById("voice");
const rateEl = document.getElementById("rate");
const filenameEl = document.getElementById("filename");
const generateEl = document.getElementById("generate");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const durationEl = document.getElementById("duration");
const playerEl = document.getElementById("player");
const downloadEl = document.getElementById("download");
const MAX_TEXT_CHARS = 8000;
const DEFAULT_RATE = "+0%";

let objectUrl = "";
let presets = [];
let selectedPresetId = "";
let loadedText = "";
let generatedPreset = null;
let optionsLoaded = false;

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function updateCount() {
  countEl.textContent = String(textEl.value.length);
}

function responseFilename(response) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Name) {
    try {
      return decodeURIComponent(utf8Name[1]);
    } catch {
      /* Fall back to the normal filename below. */
    }
  }
  const asciiName = disposition.match(/filename="?([^";]+)"?/i);
  return asciiName ? asciiName[1] : "";
}

function matchingPresetFor(text) {
  const preset = presets.find((row) => row.id === selectedPresetId);
  if (
    !preset ||
    text !== preset.text ||
    voiceEl.value !== preset.voice ||
    rateEl.value !== DEFAULT_RATE
  ) {
    return null;
  }
  return preset;
}

const RECORDING_LABELS = {
  content_only: "仅内容分类",
  keep_first_60s: "只保留前 60 秒",
  record_until_end: "录至通话结束",
};

function parseRiskWindow(window) {
  if (!window || window === "None" || window === "n/a") return { type: "none" };
  const after = window.match(/^>(\d+(?:\.\d+)?)s$/);
  if (after) return { type: "after", seconds: Number(after[1]) };
  const range = window.match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)s$/);
  if (range) {
    return { type: "range", start: Number(range[1]), end: Number(range[2]) };
  }
  return { type: "unknown", raw: window };
}

function durationVerdict(seconds, preset) {
  const problems = [];
  const notes = [];
  const min = Number(preset.target_duration_s);
  if (Number.isFinite(min) && min > 0) {
    if (seconds >= min) {
      notes.push(`时长达到目标 ≥ ${min}s`);
    } else {
      problems.push(`时长不足，目标至少 ${min}s`);
    }
  }

  const window = preset.risk_window;
  const parsed = parseRiskWindow(window);
  if (parsed.type === "after") {
    if (seconds > parsed.seconds) {
      notes.push(`已超过 ${parsed.seconds}s，满足 ${window}`);
    } else {
      problems.push(`未超过 ${parsed.seconds}s，后段风险可能还没出现`);
    }
  } else if (parsed.type === "range") {
    if (seconds >= parsed.end) {
      notes.push(`时长覆盖 ${parsed.start}–${parsed.end}s`);
    } else {
      problems.push(`未覆盖到 ${parsed.end}s，窗口 ${window} 可能不完整`);
    }
  } else if (parsed.type === "none" && !Number.isFinite(min)) {
    notes.push("无时序窗口要求");
  } else if (parsed.type === "unknown") {
    notes.push(`窗口 ${parsed.raw}`);
  }

  const ok = problems.length === 0;
  const text = (ok ? notes : problems.concat(notes)).join("；") || "时长已读取";
  return { ok, text };
}

function showPresetMeta(item) {
  if (!item) {
    presetMetaEl.classList.add("hidden");
    return;
  }
  metaCategoryEl.textContent = item.category;
  metaExpectedEl.textContent = `${item.expected}（${item.expected_scope === "first_60s" ? "前 60 秒" : item.expected_scope || "未标注"}）`;
  const target = Number(item.target_duration_s);
  metaWindowEl.textContent = Number.isFinite(target)
    ? `${item.risk_window} · 目标 ≥ ${target}s`
    : item.risk_window;
  metaRecordingEl.textContent =
    RECORDING_LABELS[item.recording_policy] || item.recording_policy || "—";
  metaNotesEl.textContent = item.notes || "—";
  presetMetaEl.classList.remove("hidden");
}

function applyPreset(item) {
  selectedPresetId = item.id;
  loadedText = item.text;
  textEl.value = item.text;
  filenameEl.value = item.filename;
  if (item.voice && [...voiceEl.options].some((option) => option.value === item.voice)) {
    voiceEl.value = item.voice;
  }
  showPresetMeta(item);
  updateCount();
}

function clearPresetSelection() {
  selectedPresetId = "";
  loadedText = textEl.value;
  showPresetMeta(null);
}

textEl.addEventListener("input", updateCount);

presetEl.addEventListener("change", () => {
  const nextId = presetEl.value;
  if (!nextId) {
    clearPresetSelection();
    return;
  }

  const item = presets.find((row) => row.id === nextId);
  if (!item) return;

  const dirty = textEl.value !== loadedText;
  if (dirty && !window.confirm("当前文案已修改，切换用例会覆盖，确定吗？")) {
    presetEl.value = selectedPresetId;
    return;
  }

  applyPreset(item);
});

playerEl.addEventListener("loadedmetadata", () => {
  const seconds = playerEl.duration;
  if (!Number.isFinite(seconds)) {
    durationEl.textContent = "时长未知";
    durationEl.className = "duration";
    return;
  }

  const lines = [`时长 ${seconds.toFixed(1)} 秒`];
  if (generatedPreset) {
    const verdict = durationVerdict(seconds, generatedPreset);
    lines.push(
      `${generatedPreset.id} · 期望 ${generatedPreset.expected} · 窗口 ${generatedPreset.risk_window}：${verdict.text}`,
    );
    durationEl.className = `duration ${verdict.ok ? "ok" : "warn"}`;
  } else {
    durationEl.className = "duration";
  }
  durationEl.textContent = lines.join("\n");
});

window.addEventListener("beforeunload", () => {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
});

async function loadOptions() {
  const [voiceRes, presetRes] = await Promise.all([
    fetch("/api/voices"),
    fetch("/api/presets"),
  ]);
  if (!voiceRes.ok || !presetRes.ok) {
    throw new Error("无法加载音色或用例列表");
  }
  const voices = await voiceRes.json();
  presets = await presetRes.json();

  const voiceOptions = document.createDocumentFragment();
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice.id;
    option.textContent = voice.label;
    voiceOptions.appendChild(option);
  }
  voiceEl.replaceChildren(voiceOptions);

  for (const item of presets) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.id} · ${item.category} · ${item.expected}`;
    presetEl.appendChild(option);
  }

  optionsLoaded = true;
  generateEl.disabled = false;
}

generateEl.addEventListener("click", async () => {
  const text = textEl.value.trim();
  if (!optionsLoaded) {
    setStatus("正在加载音色和用例，请稍候", true);
    return;
  }
  if (!text) {
    setStatus("请先粘贴文本", true);
    return;
  }
  if (text.length > MAX_TEXT_CHARS) {
    setStatus(`文本过长，最多 ${MAX_TEXT_CHARS} 个字符`, true);
    return;
  }

  generateEl.disabled = true;
  setStatus("正在合成…");
  generatedPreset = matchingPresetFor(text);
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 55_000);

  try {
    const response = await fetch("/api/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        text,
        voice: voiceEl.value,
        rate: rateEl.value,
        filename: filenameEl.value,
      }),
    });

    if (!response.ok) {
      let detail = `请求失败（${response.status}）`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }

    const blob = await response.blob();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(blob);
    playerEl.src = objectUrl;
    downloadEl.href = objectUrl;
    downloadEl.download = responseFilename(response) || "test_audio.mp3";
    durationEl.textContent = "正在读取时长…";
    durationEl.className = "duration";
    resultEl.classList.remove("hidden");
    setStatus(
      generatedPreset
        ? "合成完成，可试听或下载"
        : "合成完成，可试听或下载；自定义文本、音色或语速需人工确认时序。",
    );
  } catch (error) {
    const message = error.name === "AbortError" ? "合成超时，请缩短文本后重试" : error.message;
    setStatus(message || "合成失败", true);
  } finally {
    window.clearTimeout(timeoutId);
    generateEl.disabled = false;
  }
});

loadOptions().catch(() => {
  generateEl.disabled = true;
  setStatus("无法加载音色或用例列表，请刷新后重试", true);
});
updateCount();
