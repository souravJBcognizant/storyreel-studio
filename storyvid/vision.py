"""Structured vision calls shared by pre-production and QA.

Claude remains the default. Set VISION_PROVIDER=ollama to use a local multimodal Ollama model.
"""

import base64
import mimetypes
import os
import subprocess
import json
from pathlib import Path

import anthropic
import httpx
from pydantic import BaseModel

FALLBACK_BETA = "server-side-fallback-2026-07-01"  # re-run a declined request on a fallback model


def image_block(path: Path) -> dict:
    media = mimetypes.guess_type(Path(path).name)[0] or "image/png"
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def frame_block(video: Path, at: float, width: int = 512) -> dict:
    """One video frame at `at` seconds, as an image block."""
    png = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-f", "image2", "-vcodec", "png", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode()}}


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def vision_provider() -> str:
    return os.environ.get("VISION_PROVIDER", os.environ.get("LLM_PROVIDER", "anthropic")).strip().lower()


def vision_model() -> str:
    if vision_provider() == "ollama":
        return os.environ.get("OLLAMA_VISION_MODEL", os.environ.get("OLLAMA_MODEL", "")).strip()
    return os.environ.get("CLAUDE_MODEL", "claude-opus-5")  # read per call: the pipeline loads .env after import


def vision_configured() -> bool:
    if vision_provider() == "ollama":
        return bool(vision_model())
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _ollama_parse(content: list, schema: type[BaseModel]) -> BaseModel:
    model = vision_model()
    if not model:
        raise RuntimeError("VISION_PROVIDER=ollama needs OLLAMA_VISION_MODEL in .env")
    text, images = [], []
    for block in content:
        if block.get("type") == "text":
            text.append(block.get("text", ""))
        elif block.get("type") == "image":
            images.append(block.get("source", {}).get("data", ""))
    payload = {
        "model": model,
        "stream": False,
        "format": schema.model_json_schema(),
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": "\n\n".join(text), "images": images}],
    }
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    timeout = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "600"))
    try:
        response = httpx.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:1000]
        raise RuntimeError(
            f"Ollama vision request failed for {model!r}: {detail}. "
            "Use a multimodal model in OLLAMA_VISION_MODEL; a text-only Qwen model cannot inspect frames."
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach Ollama at {base_url}: {exc}") from exc
    raw = response.json().get("message", {}).get("content", "")
    try:
        return schema.model_validate(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Ollama returned invalid {schema.__name__} JSON: {raw[:1000]}") from exc


def parse(content: list, schema: type[BaseModel]) -> BaseModel:
    if vision_provider() == "ollama":
        return _ollama_parse(content, schema)
    if vision_provider() != "anthropic":
        raise RuntimeError(f"Unsupported VISION_PROVIDER={vision_provider()!r}; use 'anthropic' or 'ollama'")
    response = anthropic.Anthropic().beta.messages.parse(
        model=vision_model(),
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
        output_format=schema,
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined: {getattr(response.stop_details, 'explanation', '')}")
    return response.parsed_output
