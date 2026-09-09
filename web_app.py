#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import AsyncIterator, Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

try:
    import edge_tts
except ImportError as exc:
    raise SystemExit("缺少 edge-tts，请先执行：pip install edge-tts") from exc

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
PRESETS_PATH = ROOT / "presets.json"
MAX_TEXT_CHARS = 8000
DEFAULT_VOICE = "en-US-AriaNeural"
TTS_TIMEOUT_SECONDS = 45
TTS_QUEUE_TIMEOUT_SECONDS = 5
MAX_CONCURRENT_SYNTHESIS = 2
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


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str = Field(default=DEFAULT_VOICE)
    rate: str = Field(default="+0%")
    volume: str = Field(default="+0%")
    filename: str = Field(default="test_audio.mp3")


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


@app.middleware("http")
async def add_security_headers(request, call_next):
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
async def synthesize(body: SynthesizeRequest):
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
