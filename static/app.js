const textEl = document.getElementById("text");
const countEl = document.getElementById("count");
const presetEl = document.getElementById("preset");
const presetMetaEl = document.getElementById("preset-meta");
const metaCategoryEl = document.getElementById("meta-category");
const metaExpectedEl = document.getElementById("meta-expected");
const metaWindowEl = document.getElementById("meta-window");
const voiceEl = document.getElementById("voice");
const rateEl = document.getElementById("rate");
const filenameEl = document.getElementById("filename");
const generateEl = document.getElementById("generate");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const durationEl = document.getElementById("duration");
const playerEl = document.getElementById("player");
const downloadEl = document.getElementById("download");

let objectUrl = "";
let presets = [];
let selectedPresetId = "";
let loadedText = "";
let generatedPreset = null;

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function updateCount() {
  countEl.textContent = String(textEl.value.length);
}

function parseRiskWindow(window) {
  if (!window || window === "None") return { type: "none" };
  const after = window.match(/^>(\d+(?:\.\d+)?)s$/);
  if (after) return { type: "after", seconds: Number(after[1]) };
  const range = window.match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)s$/);
  if (range) {
    return { type: "range", start: Number(range[1]), end: Number(range[2]) };
  }
  return { type: "unknown", raw: window };
}

function durationVerdict(seconds, window) {
  const parsed = parseRiskWindow(window);
  if (parsed.type === "none") {
    return { ok: true, text: "无时序窗口要求" };
  }
  if (parsed.type === "after") {
    const ok = seconds > parsed.seconds;
    return {
      ok,
      text: ok
        ? `已超过 ${parsed.seconds}s，满足 ${window}`
        : `未超过 ${parsed.seconds}s，后段风险可能还没出现`,
    };
  }
  if (parsed.type === "range") {
    const ok = seconds >= parsed.end;
    return {
      ok,
      text: ok
        ? `时长覆盖 ${parsed.start}–${parsed.end}s`
        : `未覆盖到 ${parsed.end}s，窗口 ${window} 可能不完整`,
    };
  }
  return { ok: true, text: `窗口 ${parsed.raw}` };
}

function showPresetMeta(item) {
  if (!item) {
    presetMetaEl.classList.add("hidden");
    return;
  }
  metaCategoryEl.textContent = item.category;
  metaExpectedEl.textContent = item.expected;
  metaWindowEl.textContent = item.risk_window;
  presetMetaEl.classList.remove("hidden");
}

function applyPreset(item) {
  selectedPresetId = item.id;
  loadedText = item.text;
  textEl.value = item.text;
  filenameEl.value = item.filename;
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
    const verdict = durationVerdict(seconds, generatedPreset.risk_window);
    lines.push(
      `${generatedPreset.id} · 期望 ${generatedPreset.expected} · 窗口 ${generatedPreset.risk_window}：${verdict.text}`,
    );
    durationEl.className = `duration ${verdict.ok ? "ok" : "warn"}`;
  } else {
    durationEl.className = "duration";
  }
  durationEl.textContent = lines.join("\n");
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

  voiceEl.innerHTML = voices
    .map((voice) => `<option value="${voice.id}">${voice.label}</option>`)
    .join("");

  for (const item of presets) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.id} · ${item.category} · ${item.expected}`;
    presetEl.appendChild(option);
  }
}

generateEl.addEventListener("click", async () => {
  const text = textEl.value.trim();
  if (!text) {
    setStatus("请先粘贴文本", true);
    return;
  }

  generateEl.disabled = true;
  setStatus("正在合成…");
  generatedPreset = presets.find((row) => row.id === selectedPresetId) || null;

  try {
    const response = await fetch("/api/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    downloadEl.download = filenameEl.value.endsWith(".mp3")
      ? filenameEl.value
      : `${filenameEl.value}.mp3`;
    durationEl.textContent = "正在读取时长…";
    durationEl.className = "duration";
    resultEl.classList.remove("hidden");
    setStatus("合成完成，可试听或下载");
  } catch (error) {
    setStatus(error.message || "合成失败", true);
  } finally {
    generateEl.disabled = false;
  }
});

loadOptions().catch(() => setStatus("无法加载音色或用例列表", true));
updateCount();
