#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import io
import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    import edge_tts
except ImportError as exc:
    raise SystemExit("缺少 edge-tts，请先执行：pip install edge-tts") from exc

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
PRESETS_PATH = ROOT / "presets.json"
MAX_TEXT_CHARS = 8000
DEFAULT_VOICE = "en-US-AriaNeural"

DEFAULT_VOICES = [
    {"id": "en-US-AriaNeural", "label": "英语 · Aria（女）"},
    {"id": "en-US-GuyNeural", "label": "英语 · Guy（男）"},
    {"id": "en-GB-SoniaNeural", "label": "英语 · Sonia（女）"},
    {"id": "en-GB-RyanNeural", "label": "英语 · Ryan（男）"},
    {"id": "zh-CN-XiaoxiaoNeural", "label": "中文 · 晓晓（女）"},
    {"id": "zh-CN-YunxiNeural", "label": "中文 · 云希（男）"},
]


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str = Field(default=DEFAULT_VOICE)
    rate: str = Field(default="+0%")
    volume: str = Field(default="+0%")
    filename: str = Field(default="test_audio.mp3")


app = FastAPI(title="测试音频生成")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _safe_filename(name: str) -> str:
    stem = Path(name).stem.strip() or "test_audio"
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE)
    return f"{stem[:80]}.mp3"


def _validate_percent(value: str, field: str) -> str:
    if not re.fullmatch(r"[+-]\d+%", value):
        raise HTTPException(status_code=400, detail=f"{field} 格式应为 +0% 或 -10%")
    return value


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/presets")
async def presets():
    try:
        items = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="缺少 presets.json") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="presets.json 无法解析") from exc
    return items


@app.get("/api/voices")
async def voices():
    return DEFAULT_VOICES


@app.post("/api/synthesize")
async def synthesize(body: SynthesizeRequest):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="请粘贴要朗读的文本")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=400, detail=f"文本过长，最多 {MAX_TEXT_CHARS} 个字符")

    rate = _validate_percent(body.rate, "语速")
    volume = _validate_percent(body.volume, "音量")
    filename = _safe_filename(body.filename)

    communicate = edge_tts.Communicate(
        text=text,
        voice=body.voice,
        rate=rate,
        volume=volume,
    )

    audio = bytearray()
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"语音合成失败：{exc}") from exc

    if not audio:
        raise HTTPException(status_code=502, detail="未生成到音频数据")

    return StreamingResponse(
        io.BytesIO(bytes(audio)),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
