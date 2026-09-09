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
const aiModelEl = document.getElementById("ai-model");
const aiCategoryEl = document.getElementById("ai-category");
const aiLanguageEl = document.getElementById("ai-language");
const aiExpectedEl = document.getElementById("ai-expected");
const aiRiskWindowEl = document.getElementById("ai-risk-window");
const aiDurationEl = document.getElementById("ai-duration");
const aiInstructionsEl = document.getElementById("ai-instructions");
const aiAutoSynthesizeEl = document.getElementById("ai-auto-synthesize");
const aiGenerateEl = document.getElementById("ai-generate");
const aiTestConnectionEl = document.getElementById("ai-test-connection");
const aiOptimizeEl = document.getElementById("ai-optimize");
const aiStatusEl = document.getElementById("ai-status");
const manifestEl = document.getElementById("download-manifest");
const MAX_TEXT_CHARS = 8000;
const DEFAULT_RATE = "+0%";

let objectUrl = "";
let presets = [];
let selectedPresetId = "";
let loadedText = "";
let validationCase = null;
let lastGeneratedCase = null;
let lastSynthesis = null;
let manifestUrl = "";
let optionsLoaded = false;
let activeSynthesisController = null;
let activeAiController = null;

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function setAiStatus(message, isError = false) {
  aiStatusEl.textContent = message;
  aiStatusEl.classList.toggle("error", isError);
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

const RISK_WINDOW_MINIMUMS = {
  "0-20s": 20,
  "20-40s": 40,
  "40-60s": 60,
  "0-60s": 60,
  ">60s": 61,
};

function preferredVoice(language) {
  return language === "zh" ? "zh-CN-XiaoxiaoNeural" : "en-US-AriaNeural";
}

function matchingGeneratedCaseFor(text) {
  if (
    !lastGeneratedCase ||
    text !== lastGeneratedCase.text ||
    voiceEl.value !== lastGeneratedCase.voice ||
    rateEl.value !== lastGeneratedCase.rate
  ) {
    return null;
  }
  return lastGeneratedCase;
}

function updateManifest(durationSeconds) {
  if (!lastSynthesis) return;
  const manifest = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    ...lastSynthesis,
    actual_duration_s: Number(durationSeconds.toFixed(1)),
  };
  if (manifestUrl) URL.revokeObjectURL(manifestUrl);
  manifestUrl = URL.createObjectURL(
    new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" }),
  );
  manifestEl.href = manifestUrl;
  manifestEl.download = `${PathSafeFilename(lastSynthesis.filename)}.json`;
  manifestEl.classList.remove("hidden");
}

function PathSafeFilename(filename) {
  return filename.replace(/\.mp3$/i, "") || "test_case";
}

function updateTargetDurationForWindow() {
  const minimum = RISK_WINDOW_MINIMUMS[aiRiskWindowEl.value] || 5;
  if (Number(aiDurationEl.value) < minimum) aiDurationEl.value = minimum;
}

function syncAiControls() {
  if (aiExpectedEl.value === "Normal") {
    aiRiskWindowEl.value = "n/a";
    aiRiskWindowEl.disabled = true;
  } else {
    aiRiskWindowEl.disabled = false;
    if (aiRiskWindowEl.value === "n/a") aiRiskWindowEl.value = "0-20s";
  }
  updateTargetDurationForWindow();
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
aiLanguageEl.addEventListener("change", () => {
  const voice = preferredVoice(aiLanguageEl.value);
  if ([...voiceEl.options].some((option) => option.value === voice)) voiceEl.value = voice;
});
aiExpectedEl.addEventListener("change", syncAiControls);
aiRiskWindowEl.addEventListener("change", updateTargetDurationForWindow);

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
  if (validationCase) {
    const verdict = durationVerdict(seconds, validationCase);
    lines.push(
      `${validationCase.id} · 期望 ${validationCase.expected} · 窗口 ${validationCase.risk_window}：${verdict.text}`,
    );
    durationEl.className = `duration ${verdict.ok ? "ok" : "warn"}`;
    aiOptimizeEl.classList.toggle("hidden", verdict.ok || !lastGeneratedCase);
    if (!verdict.ok && lastGeneratedCase) {
      aiOptimizeEl.dataset.actualDuration = String(seconds);
    }
  } else {
    durationEl.className = "duration";
    aiOptimizeEl.classList.add("hidden");
  }
  durationEl.textContent = lines.join("\n");
  updateManifest(seconds);
});

window.addEventListener("beforeunload", () => {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  if (manifestUrl) URL.revokeObjectURL(manifestUrl);
});

async function loadOptions() {
  const [voiceRes, presetRes, modelRes, categoryRes] = await Promise.all([
    fetch("/api/voices"),
    fetch("/api/presets"),
    fetch("/api/models"),
    fetch("/api/risk-categories"),
  ]);
  if (!voiceRes.ok || !presetRes.ok || !modelRes.ok || !categoryRes.ok) {
    throw new Error("无法加载音色或用例列表");
  }
  const voices = await voiceRes.json();
  presets = await presetRes.json();
  const models = await modelRes.json();
  const categories = await categoryRes.json();

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

  const modelOptions = document.createDocumentFragment();
  for (const model of models) {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    modelOptions.appendChild(option);
  }
  aiModelEl.replaceChildren(modelOptions);
  aiModelEl.disabled = models.length === 0;

  const categoryOptions = document.createDocumentFragment();
  for (const category of categories) {
    const option = document.createElement("option");
    option.value = category.id;
    option.textContent = category.label;
    option.title = category.description;
    categoryOptions.appendChild(option);
  }
  aiCategoryEl.replaceChildren(categoryOptions);
  aiCategoryEl.disabled = categories.length === 0;
  aiGenerateEl.disabled = models.length === 0 || categories.length === 0;
  aiTestConnectionEl.disabled = models.length === 0;
  if (models.length === 0) {
    setAiStatus("尚未配置 AI 密钥：请按 README 创建并加载本地 .env 文件。", true);
  }

  optionsLoaded = true;
  generateEl.disabled = false;
  syncAiControls();
}

async function synthesizeAudio() {
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
  validationCase = matchingPresetFor(text) || matchingGeneratedCaseFor(text);
  aiOptimizeEl.classList.add("hidden");
  manifestEl.classList.add("hidden");
  if (manifestUrl) {
    URL.revokeObjectURL(manifestUrl);
    manifestUrl = "";
  }
  const controller = new AbortController();
  activeSynthesisController = controller;
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
    lastSynthesis = {
      filename: downloadEl.download,
      text,
      voice: voiceEl.value,
      rate: rateEl.value,
      volume: "+0%",
      validation_case: validationCase
        ? {
            id: validationCase.id,
            category: validationCase.category,
            expected: validationCase.expected,
            risk_window: validationCase.risk_window,
            target_duration_s: validationCase.target_duration_s,
          }
        : null,
      ai_generation: matchingGeneratedCaseFor(text)
        ? {
            provider: lastGeneratedCase.provider,
            model: lastGeneratedCase.model,
            language: lastGeneratedCase.language,
            category: lastGeneratedCase.category,
            expected: lastGeneratedCase.expected,
            risk_window: lastGeneratedCase.risk_window,
            target_duration_s: lastGeneratedCase.target_duration_s,
            extra_instructions: aiInstructionsEl.value.trim() || null,
          }
        : null,
    };
    durationEl.textContent = "正在读取时长…";
    durationEl.className = "duration";
    resultEl.classList.remove("hidden");
    setStatus(
      validationCase
        ? "合成完成，可试听或下载"
        : "合成完成，可试听或下载；自定义文本、音色或语速需人工确认时序。",
    );
  } catch (error) {
    const message = error.name === "AbortError" ? "合成超时，请缩短文本后重试" : error.message;
    setStatus(message || "合成失败", true);
  } finally {
    window.clearTimeout(timeoutId);
    if (activeSynthesisController === controller) activeSynthesisController = null;
    generateEl.disabled = false;
  }
}

generateEl.addEventListener("click", () => {
  void synthesizeAudio();
});

async function generateAiText(extraInstructions = "") {
  const targetDuration = Number(aiDurationEl.value);
  if (!Number.isInteger(targetDuration) || targetDuration < 5 || targetDuration > 120) {
    setAiStatus("目标时长应为 5 到 120 秒之间的整数", true);
    return;
  }

  aiGenerateEl.disabled = true;
  setAiStatus("正在生成测试文案…");
  const controller = new AbortController();
  activeAiController = controller;
  const timeoutId = window.setTimeout(() => controller.abort(), 55_000);
  try {
    const response = await fetch("/api/generate-text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        provider: aiModelEl.value,
        category: aiCategoryEl.value,
        language: aiLanguageEl.value,
        expected: aiExpectedEl.value,
        risk_window: aiRiskWindowEl.value,
        target_duration_s: targetDuration,
        extra_instructions: [aiInstructionsEl.value.trim(), extraInstructions].filter(Boolean).join("\n"),
      }),
    });
    if (!response.ok) {
      let detail = `请求失败（${response.status}）`;
      try {
        detail = (await response.json()).detail || detail;
      } catch {
        /* Ignore a non-JSON error response. */
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    textEl.value = payload.text;
    presetEl.value = "";
    clearPresetSelection();
    const voice = preferredVoice(aiLanguageEl.value);
    if ([...voiceEl.options].some((option) => option.value === voice)) voiceEl.value = voice;
    rateEl.value = DEFAULT_RATE;
    filenameEl.value = `AI_${aiCategoryEl.value}_${Date.now()}.mp3`;
    lastGeneratedCase = {
      ...payload.case,
      text: payload.text,
      voice: voiceEl.value,
      rate: rateEl.value,
      provider: payload.provider,
      model: payload.model,
      language: aiLanguageEl.value,
    };
    updateCount();
    setAiStatus(`文案已由 ${payload.model} 生成${aiAutoSynthesizeEl.checked ? "，正在合成音频…" : "。"}`);
    if (aiAutoSynthesizeEl.checked) await synthesizeAudio();
  } catch (error) {
    const message = error.name === "AbortError" ? "AI 生成超时，请稍后重试" : error.message;
    setAiStatus(message || "AI 文本生成失败", true);
  } finally {
    window.clearTimeout(timeoutId);
    if (activeAiController === controller) activeAiController = null;
    aiGenerateEl.disabled = aiModelEl.disabled || aiCategoryEl.disabled;
  }
}

aiGenerateEl.addEventListener("click", () => {
  void generateAiText();
});

aiTestConnectionEl.addEventListener("click", async () => {
  if (!aiModelEl.value) return;
  aiTestConnectionEl.disabled = true;
  setAiStatus("正在测试模型连接…");
  try {
    const response = await fetch(`/api/models/${encodeURIComponent(aiModelEl.value)}/test`, {
      method: "POST",
    });
    if (!response.ok) {
      let detail = `请求失败（${response.status}）`;
      try {
        detail = (await response.json()).detail || detail;
      } catch {
        /* Ignore a non-JSON error response. */
      }
      throw new Error(detail);
    }
    const payload = await response.json();
    setAiStatus(`${payload.label} 连接正常。`);
  } catch (error) {
    setAiStatus(error.message || "模型连接失败", true);
  } finally {
    aiTestConnectionEl.disabled = aiModelEl.disabled;
  }
});

aiOptimizeEl.addEventListener("click", () => {
  const actualDuration = Number(aiOptimizeEl.dataset.actualDuration);
  const targetDuration = Number(aiDurationEl.value);
  if (!Number.isFinite(actualDuration) || !Number.isFinite(targetDuration)) return;
  const adjustment = actualDuration < targetDuration ? "扩写" : "缩短";
  void generateAiText(
    `上一版实际朗读时长为 ${actualDuration.toFixed(1)} 秒，目标至少 ${targetDuration} 秒。请在不改变风险类型、预期和风险窗口的前提下${adjustment}文案，并只输出 JSON。`,
  );
});

loadOptions().catch(() => {
  generateEl.disabled = true;
  aiGenerateEl.disabled = true;
  aiTestConnectionEl.disabled = true;
  setStatus("无法加载音色或用例列表，请刷新后重试", true);
});
updateCount();
