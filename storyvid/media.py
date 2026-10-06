"""LTX renders (through the ltx-2-mlx CLI) and the ffmpeg helpers around them.

Renders are cached by a hash of everything that affects the pixels, so re-running a plan
only renders what changed.
"""

import hashlib
import io
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def frames_for(seconds: float, fps: int) -> int:
    """Smallest frame count on LTX's 8k+1 grid that covers `seconds`."""
    return 8 * math.ceil((math.ceil(seconds * fps) - 1) / 8) + 1


def file_sha1(path: Path) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


@dataclass
class RenderResult:
    path: Path
    seconds: float  # wall time; 0 when served from the cache
    cached: bool


class Renderer:
    def __init__(self, project: Path, model_dir: Path, runtime_dir: Path, width: int, height: int, fps: int):
        self.project = project
        self.model_dir = model_dir
        self.runtime_dir = runtime_dir
        self.width, self.height, self.fps = width, height, fps
        self.runtime_rev = subprocess.run(
            ["git", "-C", str(runtime_dir), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()

    def cache_key(self, prompt: str, seed: int, frames: int | None, image: Path | None) -> str:
        spec = {
            "prompt": prompt,
            "seed": seed,
            "frames": frames,
            "auto_duration": "3:8" if frames is None else None,
            "size": [self.width, self.height, self.fps],
            "model": self.model_dir.name,
            "runtime": self.runtime_rev,
            "image": file_sha1(image) if image else None,
        }
        return hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]

    def render(self, prompt: str, out: Path, seed: int, frames: int | None, image: Path | None) -> RenderResult:
        if out.exists():
            return RenderResult(out, 0.0, True)
        cmd = [
            "uv", "run", "--project", str(self.runtime_dir), "ltx-2-mlx", "generate", "--distilled",
            "--model", str(self.model_dir), "-p", prompt,
            "-H", str(self.height), "-W", str(self.width), "--frame-rate", str(self.fps),
            "--seed", str(seed), "--low-ram", "-o", str(out.with_suffix(".partial.mp4")),
        ]  # fmt: skip
        cmd += ["-f", str(frames)] if frames else ["--auto-duration", "3:8"]
        if image:
            cmd += ["-i", str(image)]
        t0 = time.perf_counter()
        with open(out.with_suffix(".log"), "w") as log:
            proc = subprocess.run(cmd, cwd=self.project, stdout=log, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            raise RuntimeError(f"LTX render failed ({proc.returncode}); see {out.with_suffix('.log')}")
        out.with_suffix(".partial.mp4").rename(out)  # only complete renders ever land in the cache
        return RenderResult(out, time.perf_counter() - t0, False)


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(out.stdout)


def last_frame(video: Path, png: Path) -> Path:
    ffmpeg("-sseof", "-0.5", "-i", str(video), "-update", "1", str(png))
    return png


def extract_audio(video: Path, wav: Path) -> Path:
    """Mono 24 kHz 16-bit — what the voice and speech models expect."""
    ffmpeg("-i", str(video), "-vn", "-ac", "1", "-ar", "24000", "-sample_fmt", "s16", str(wav))
    return wav


def frames(video: Path, fps: float = 2) -> list[Image.Image]:
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"fps={fps}",
         "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return [Image.open(io.BytesIO(PNG_MAGIC + c)).convert("RGB") for c in raw.split(PNG_MAGIC)[1:]]


def contact_sheet(video: Path, png: Path, fps: float = 2, cols: int = 4) -> Path:
    n = max(1, round(duration(video) * fps))  # what ffmpeg's fps filter actually emits; ceil left an empty row
    rows = math.ceil(n / cols)
    ffmpeg("-i", str(video), "-vf", f"fps={fps},scale=288:-1,tile={cols}x{rows}", "-frames:v", "1", str(png))
    return png
