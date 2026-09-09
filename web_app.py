#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import AsyncIterator, Literal, TypedDict
from urllib.parse import quote

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

try:
    import edge_tts
except ImportError as exc:
    raise SystemExit("缺少 edge-tts，请先执行：pip install edge-tts") from exc

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
PRESETS_PATH = ROOT / "presets.json"
load_dotenv(ROOT / ".env")
MAX_TEXT_CHARS = 8000
DEFAULT_VOICE = "en-US-AriaNeural"
TTS_TIMEOUT_SECONDS = 45
TTS_QUEUE_TIMEOUT_SECONDS = 5
MAX_CONCURRENT_SYNTHESIS = 2
AI_TIMEOUT_SECONDS = 45
AI_QUEUE_TIMEOUT_SECONDS = 5
MAX_CONCURRENT_AI_GENERATIONS = 2
MAX_REQUESTS_PER_MINUTE = 20
ALLOW_REMOTE_ACCESS = os.environ.get("ALLOW_REMOTE_ACCESS", "").lower() == "true"
LOGGER = logging.getLogger(__name__)

DEFAULT_VOICES = [
    {"id": "en-US-AriaNeural", "label": "英语 · Aria（女）"},
    {"id": "en-US-GuyNeural", "label": "英语 · Guy（男）"},
    {"id": "en-GB-SoniaNeural", "label": "英语 · Sonia（女）"},
    {"id": "en-GB-RyanNeural", "label": "英语 · Ryan（男）"},
    {"id": "zh-CN-XiaoxiaoNeural", "label": "中文 · 晓晓（女）"},
    {"id": "zh-CN-YunxiNeural", "label": "中文 · 云希（男）"},
]
VOICE_IDS = frozenset(voice["id"] for voice in DEFAULT_VOICES)
PRESET_CACHE: list["Preset"] | None = None
PRESET_CACHE_MTIME_NS: int | None = None
TTS_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_SYNTHESIS)
AI_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_AI_GENERATIONS)
RATE_LIMIT_LOCK = asyncio.Lock()
RATE_LIMIT_EVENTS: dict[tuple[str, str], deque[float]] = defaultdict(deque)


class ModelConfig(TypedDict):
    id: str
    label: str
    protocol: Literal["openai"]
    api_key_env: str
    base_url: str
    model: str


MODEL_CONFIGS: tuple[ModelConfig, ...] = (
    {
        "id": "agnes",
        "label": "Agnes 3.0 Flash",
        "protocol": "openai",
        "api_key_env": "AGNES_API_KEY",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "model": "agnes-3.0-flash",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek V4 Flash",
        "protocol": "openai",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
    },
    {
        "id": "kimi",
        "label": "Kimi K2.6",
        "protocol": "openai",
        "api_key_env": "KIMI_API_KEY",
        "base_url": "https://api.moonshot.ai/v1",
        "model": "kimi-k2.6",
    },
    {
        "id": "gemini",
        "label": "Gemini 3.8 Flash",
        "protocol": "openai",
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
    },
)

RISK_CATEGORIES = (
    {
        "id": "financial_fraud",
        "label": "金融诈骗",
        "description": "冒充机构、索要验证码、诱导转账或虚假投资。",
    },
    {
        "id": "identity_account_risk",
        "label": "身份与账户风险",
        "description": "账号接管、冒用身份或可疑账户操作。",
    },
    {
        "id": "money_laundering",
        "label": "洗钱与可疑资金",
        "description": "可疑资金流转、代收代付或掩饰来源。",
    },
    {
        "id": "gambling",
        "label": "赌博与下注",
        "description": "招揽下注、赌博交易或代充代投。",
    },
    {
        "id": "controlled_substances",
        "label": "毒品交易",
        "description": "非法受控物质的交易或招揽。",
    },
    {
        "id": "violent_threats",
        "label": "暴力威胁",
        "description": "针对个人的伤害、恐吓或暴力威胁。",
    },
    {
        "id": "public_safety",
        "label": "公共安全威胁",
        "description": "非操作性的公共安全与恐袭风险表达。",
    },
    {
        "id": "harassment_hate",
        "label": "骚扰与仇恨言论",
        "description": "辱骂、骚扰或歧视性攻击的检测语境。",
    },
    {
        "id": "self_harm_crisis",
        "label": "自伤危机",
        "description": "自伤风险识别与转介求助语境。",
    },
    {
        "id": "normal_reference",
        "label": "正常 / 误报对照",
        "description": "新闻转述、反诈教育、历史讨论等不应触发的文本。",
    },
)
RISK_CATEGORY_IDS = frozenset(category["id"] for category in RISK_CATEGORIES)
RISK_WINDOWS: dict[str, int | None] = {
    "n/a": None,
    "0-20s": 20,
    "20-40s": 40,
    "40-60s": 60,
    "0-60s": 60,
    ">60s": 61,
}


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str = Field(default=DEFAULT_VOICE)
    rate: str = Field(default="+0%")
    volume: str = Field(default="+0%")
    filename: str = Field(default="test_audio.mp3")


class GenerateTextRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    category: str = Field(min_length=1, max_length=64)
    language: Literal["zh", "en"] = "zh"
    expected: Literal["Risk", "Normal"] = "Risk"
    risk_window: str = Field(default="0-20s", max_length=16)
    target_duration_s: int = Field(default=30, ge=5, le=120)
    extra_instructions: str = Field(default="", max_length=1000)


class GeneratedScript(BaseModel):
    """The deliberately small output contract expected from a text model."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class Preset(BaseModel):
    """The versioned contract for a regression-test case in presets.json."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^T\d{2}$")
    filename: str = Field(min_length=1)
    category: str = Field(min_length=1)
    language: Literal["en", "zh"]
    voice: str
    expected: Literal["Risk", "Normal"]
    expected_scope: Literal["first_60s"]
    risk_window: str = Field(min_length=1)
    target_duration_s: float = Field(gt=0)
    recording_policy: Literal["content_only", "keep_first_60s", "record_until_end"]
    notes: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class TTSProviderError(Exception):
    """A provider failure that is safe to turn into a client-facing response."""


class AIProviderError(Exception):
    """A model-provider failure that is safe to show to an end user."""


PRESET_LIST_ADAPTER: TypeAdapter[list[Preset]] = TypeAdapter(list[Preset])


app = FastAPI(title="测试音频生成")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _safe_filename(name: str) -> str:
    stem = Path(name).stem.strip() or "test_audio"
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE)
    return f"{stem[:80]}.mp3"


def _content_disposition(filename: str) -> str:
    """Return a standards-compliant header for both ASCII and Unicode filenames."""
    ascii_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(filename).stem).strip("_-")
    ascii_filename = f"{ascii_stem or 'test_audio'}.mp3"
    return (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def _validate_percent(value: str, field: str, minimum: int = -100, maximum: int = 100) -> str:
    match = re.fullmatch(r"([+-])(\d+)%", value)
    if not match:
        raise HTTPException(status_code=400, detail=f"{field} 格式应为 +0% 或 -10%")
    percent = int(match.group(1) + match.group(2))
    if not minimum <= percent <= maximum:
        raise HTTPException(
            status_code=400,
            detail=f"{field} 必须介于 {minimum}% 和 +{maximum}% 之间",
        )
    return value


def _load_presets() -> list[Preset]:
    """Validate and cache preset data, refreshing it after a local edit in reload mode."""
    global PRESET_CACHE, PRESET_CACHE_MTIME_NS

    try:
        mtime_ns = PRESETS_PATH.stat().st_mtime_ns
        if PRESET_CACHE is not None and PRESET_CACHE_MTIME_NS == mtime_ns:
            return PRESET_CACHE
        data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
        items = PRESET_LIST_ADAPTER.validate_python(data)
    except (FileNotFoundError, json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError("presets.json 缺失、格式错误或不符合预设 schema") from exc

    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise RuntimeError("presets.json 包含重复的用例 ID")
    unknown_voices = sorted({item.voice for item in items} - VOICE_IDS)
    if unknown_voices:
        raise RuntimeError(f"presets.json 使用了未配置的音色：{', '.join(unknown_voices)}")

    PRESET_CACHE = items
    PRESET_CACHE_MTIME_NS = mtime_ns
    return items


def _configured_models() -> list[dict[str, str]]:
    """Expose enabled model metadata without ever returning credentials."""
    return [
        {"id": config["id"], "label": config["label"]}
        for config in MODEL_CONFIGS
        if os.environ.get(config["api_key_env"])
    ]


def _model_config(provider_id: str) -> ModelConfig | None:
    return next((config for config in MODEL_CONFIGS if config["id"] == provider_id), None)


def _generation_prompt(body: GenerateTextRequest) -> str:
    category = next(category for category in RISK_CATEGORIES if category["id"] == body.category)
    language = "简体中文" if body.language == "zh" else "English"
    expected = "应触发 Risk" if body.expected == "Risk" else "应作为 Normal 的误报对照"
    extra = body.extra_instructions.strip() or "无"
    return f"""为已授权的语音风控回归测试生成一段可直接朗读的文本。

类别：{category['label']}（{category['description']}）
语言：{language}
检测预期：{expected}
风险窗口：{body.risk_window}。
目标朗读时长：约 {body.target_duration_s} 秒。
额外要求：{extra}

严格只返回 JSON 对象 `{{"text":"..."}}`，不得输出 Markdown、标题或其他字段。文本必须是虚构测试内容：不得使用真实人物、真实机构账号、真实地址或联系方式；不得提供暴力实施、武器制作、规避执法或犯罪执行的操作步骤。对公共安全和暴力类别只使用非操作性的风险表达。文案应自然、口语化，并与指定语言一致。若风险窗口不是 n/a，应把触发性表达安排在该窗口内；若预期是 Normal，不得加入触发性表达。"""


def _parse_generated_script(raw: str) -> str:
    """Accept only the documented JSON response, never arbitrary model chatter."""
    candidate = raw.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("\n", 1)[0].strip()
    try:
        return GeneratedScript.model_validate_json(candidate).text.strip()
    except (ValidationError, ValueError) as exc:
        raise AIProviderError from exc


async def _read_provider_response(response: aiohttp.ClientResponse) -> dict:
    try:
        payload = await response.json(content_type=None)
    except (aiohttp.ContentTypeError, json.JSONDecodeError) as exc:
        raise AIProviderError from exc
    if response.status >= 400:
        LOGGER.warning("AI provider returned HTTP %s", response.status)
        raise AIProviderError
    if not isinstance(payload, dict):
        raise AIProviderError
    return payload


async def _generate_with_model(config: ModelConfig, prompt: str) -> str:
    api_key = os.environ.get(config["api_key_env"])
    if not api_key:
        raise AIProviderError

    timeout = aiohttp.ClientTimeout(total=AI_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if config["protocol"] == "openai":
                async with session.post(
                    f"{config['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": config["model"],
                        "messages": [
                            {"role": "system", "content": "You generate safe, fictional regression-test speech scripts."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1200,
                        "response_format": {"type": "json_object"},
                    },
                ) as response:
                    payload = await _read_provider_response(response)
                text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        LOGGER.warning("AI provider request failed: %s", type(exc).__name__)
        raise AIProviderError from exc

    return _parse_generated_script(str(text))


def _request_client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _enforce_rate_limit(request: Request, bucket: str) -> None:
    """A small local guardrail; public deployments still require real authentication."""
    now = time.monotonic()
    key = (_request_client_id(request), bucket)
    async with RATE_LIMIT_LOCK:
        events = RATE_LIMIT_EVENTS[key]
        while events and now - events[0] >= 60:
            events.popleft()
        if len(events) >= MAX_REQUESTS_PER_MINUTE:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
        events.append(now)


@app.middleware("http")
async def add_security_headers(request, call_next):
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    if not ALLOW_REMOTE_ACCESS and request.client and request.client.host not in loopback_hosts:
        return JSONResponse(status_code=403, content={"detail": "仅允许本机访问"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; media-src 'self' blob:; style-src 'self'; "
        "script-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/presets")
async def presets():
    try:
        items = _load_presets()
    except RuntimeError as exc:
        LOGGER.exception("Unable to load presets")
        raise HTTPException(status_code=500, detail="预设文件不可用，请联系维护者") from exc
    return items


@app.get("/api/voices")
async def voices():
    return DEFAULT_VOICES


@app.get("/api/models")
async def models():
    return _configured_models()


@app.get("/api/risk-categories")
async def risk_categories():
    return RISK_CATEGORIES


@app.post("/api/models/{provider_id}/test")
async def test_model_connection(provider_id: str, request: Request):
    """Perform a tiny real request so a configured key is not mistaken for a working one."""
    config = _model_config(provider_id)
    if not config or not os.environ.get(config["api_key_env"]):
        raise HTTPException(status_code=400, detail="所选模型尚未配置")

    await _enforce_rate_limit(request, "ai")
    try:
        await asyncio.wait_for(AI_SEMAPHORE.acquire(), timeout=AI_QUEUE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise HTTPException(status_code=429, detail="当前生成任务较多，请稍后重试") from exc
    try:
        await _generate_with_model(
            config,
            '连接检查：严格只返回 JSON 对象 {"text":"ok"}。',
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail="模型连接失败，请检查密钥、模型权限或网络") from exc
    finally:
        AI_SEMAPHORE.release()
    return {"provider": config["id"], "label": config["label"], "status": "ok"}


@app.post("/api/generate-text")
async def generate_text(body: GenerateTextRequest, request: Request):
    if body.category not in RISK_CATEGORY_IDS:
        raise HTTPException(status_code=400, detail="不支持的风险类型")
    if body.risk_window not in RISK_WINDOWS:
        raise HTTPException(status_code=400, detail="不支持的风险窗口")
    required_duration = RISK_WINDOWS[body.risk_window]
    if required_duration and body.target_duration_s < required_duration:
        raise HTTPException(status_code=400, detail=f"风险窗口 {body.risk_window} 需要至少 {required_duration} 秒的目标时长")
    config = _model_config(body.provider)
    if not config or not os.environ.get(config["api_key_env"]):
        raise HTTPException(status_code=400, detail="所选模型尚未配置")

    await _enforce_rate_limit(request, "ai")
    try:
        await asyncio.wait_for(AI_SEMAPHORE.acquire(), timeout=AI_QUEUE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise HTTPException(status_code=429, detail="当前生成任务较多，请稍后重试") from exc
    try:
        text = await _generate_with_model(config, _generation_prompt(body))
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail="AI 文本生成失败，请检查密钥或稍后重试") from exc
    finally:
        AI_SEMAPHORE.release()

    category = next(item for item in RISK_CATEGORIES if item["id"] == body.category)
    return {
        "text": text,
        "provider": config["id"],
        "model": config["label"],
        "case": {
            "id": f"AI-{body.category}",
            "category": category["label"],
            "expected": body.expected,
            "expected_scope": "first_60s",
            "risk_window": body.risk_window,
            "target_duration_s": body.target_duration_s,
            "recording_policy": "content_only",
            "notes": f"由 {config['label']} 生成；请结合实际音频时长复核。",
            "text": text,
        },
    }


async def _stream_audio(communicate: edge_tts.Communicate) -> AsyncIterator[bytes]:
    """Relay provider audio without retaining the completed MP3 in process memory."""
    started_at = asyncio.get_running_loop().time()
    source = communicate.stream()
    try:
        while True:
            remaining = TTS_TIMEOUT_SECONDS - (asyncio.get_running_loop().time() - started_at)
            if remaining <= 0:
                raise TimeoutError
            try:
                chunk = await asyncio.wait_for(anext(source), timeout=remaining)
            except StopAsyncIteration:
                return
            if chunk["type"] == "audio":
                yield chunk["data"]
    except TimeoutError as exc:
        LOGGER.warning("Edge TTS timed out after %s seconds", TTS_TIMEOUT_SECONDS)
        raise TTSProviderError from exc
    except Exception as exc:
        LOGGER.exception("Edge TTS synthesis failed")
        raise TTSProviderError from exc
    finally:
        await source.aclose()
        TTS_SEMAPHORE.release()


async def _prepend(first_chunk: bytes, chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    yield first_chunk
    async for chunk in chunks:
        yield chunk


@app.post("/api/synthesize")
async def synthesize(body: SynthesizeRequest, request: Request):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="请粘贴要朗读的文本")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=400, detail=f"文本过长，最多 {MAX_TEXT_CHARS} 个字符")

    if body.voice not in VOICE_IDS:
        raise HTTPException(status_code=400, detail="不支持的音色")
    rate = _validate_percent(body.rate, "语速")
    volume = _validate_percent(body.volume, "音量")
    filename = _safe_filename(body.filename)

    await _enforce_rate_limit(request, "tts")
    try:
        await asyncio.wait_for(TTS_SEMAPHORE.acquire(), timeout=TTS_QUEUE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise HTTPException(status_code=429, detail="当前合成任务较多，请稍后重试") from exc

    try:
        communicate = edge_tts.Communicate(
            text=text,
            voice=body.voice,
            rate=rate,
            volume=volume,
        )
        chunks = _stream_audio(communicate)
        first_chunk = await anext(chunks)
    except StopAsyncIteration as exc:
        raise HTTPException(status_code=502, detail="未生成到音频数据") from exc
    except TTSProviderError as exc:
        raise HTTPException(status_code=502, detail="语音服务暂时不可用，请稍后重试") from exc
    except Exception:
        TTS_SEMAPHORE.release()
        LOGGER.exception("Unable to initialize Edge TTS")
        raise HTTPException(status_code=502, detail="语音服务暂时不可用，请稍后重试") from None

    return StreamingResponse(
        _prepend(first_chunk, chunks),
        media_type="audio/mpeg",
        headers={"Content-Disposition": _content_disposition(filename)},
    )
