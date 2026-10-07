"""Claude vision calls with structured output, shared by pre-production (frame analysis, keyframe review)
and QA (who is speaking in a take)."""

import base64
import mimetypes
import os
import subprocess
from pathlib import Path

import anthropic
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


def vision_model() -> str:
    return os.environ.get("CLAUDE_MODEL", "claude-opus-5")  # read per call: the pipeline loads .env after import


def parse(content: list, schema: type[BaseModel]) -> BaseModel:
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
