"""The file browser: virtual paths ("<root>/<rel>") over a fixed set of roots, plus thumbnails.

Nothing outside FILE_ROOTS is ever listed or served.
"""

import hashlib
import mimetypes
import subprocess
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from .config import CACHE, FILE_ROOTS

KINDS = {
    "video": {".mp4", ".mov", ".m4v", ".webm"},
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    "audio": {".wav", ".mp3", ".m4a", ".flac", ".aac"},
    "text": {".md", ".json", ".jsonl", ".log", ".txt", ".hocon", ".yaml", ".yml", ".csv", ".py", ".sh"},
}
_durations: dict[tuple[str, float], float | None] = {}


def kind_of(path: Path) -> str:
    if path.is_dir():
        return "dir"
    ext = path.suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), "other")


def resolve(vpath: str) -> Path:
    """Virtual path → absolute path, refusing anything that escapes its root."""
    root_key, _, rel = vpath.strip("/").partition("/")
    root = FILE_ROOTS.get(root_key)
    if root is None:
        raise HTTPException(404, f"unknown root {root_key!r}")
    path = (root / rel).resolve()
    if path != root.resolve() and root.resolve() not in path.parents:
        raise HTTPException(403, "path outside the allowed roots")
    if not path.exists():
        raise HTTPException(404, "not found")
    return path


def to_virtual(path: Path | str | None) -> str | None:
    if path is None:
        return None
    path = Path(path).resolve()
    for key, root in FILE_ROOTS.items():
        root = root.resolve()
        if path == root or root in path.parents:
            rel = path.relative_to(root).as_posix()
            return key if rel == "." else f"{key}/{rel}"
    return None


def media_duration(path: Path) -> float | None:
    key = (str(path), path.stat().st_mtime)
    if key not in _durations:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True,
        )  # fmt: skip
        try:
            _durations[key] = round(float(out.stdout.strip()), 2)
        except ValueError:
            _durations[key] = None
    return _durations[key]


def entry(path: Path) -> dict:
    kind = kind_of(path)
    stat = path.stat()
    return {
        "name": path.name,
        "path": to_virtual(path),
        "kind": kind,
        "size": None if kind == "dir" else stat.st_size,
        "modified": stat.st_mtime,
        "duration": media_duration(path) if kind in ("video", "audio") else None,
        "items": sum(1 for p in path.iterdir() if not p.name.startswith(".")) if kind == "dir" else None,
    }


def listing(vpath: str) -> dict:
    path = resolve(vpath)
    if not path.is_dir():
        raise HTTPException(400, "not a directory")
    children = [p for p in path.iterdir() if not p.name.startswith(".") and ".partial." not in p.name]
    children.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
    parent = to_virtual(path.parent) if vpath.strip("/").count("/") else None
    return {"path": to_virtual(path), "parent": parent, "entries": [entry(p) for p in children]}


def roots() -> list[dict]:
    labels = {"productions": "Productions", "stage0": "Stage 0 · model tests", "stage1": "Stage 1 · first film"}
    return [{"key": k, "label": labels.get(k, k), "exists": r.exists()} for k, r in FILE_ROOTS.items()]


def thumbnail(vpath: str, at: float = 1.0, width: int = 480) -> Path:
    """Cached JPEG still of a video (frame at `at` s, clamped to the clip) or a downscaled image."""
    path = resolve(vpath)
    kind = kind_of(path)
    if kind not in ("video", "image"):
        raise HTTPException(400, "no thumbnail for this file type")
    key = hashlib.sha1(f"{path}|{path.stat().st_mtime}|{at}|{width}".encode()).hexdigest()[:16]
    out = CACHE / "thumbs" / f"{key}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    if kind == "image":
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((width, width * 4))
            im.save(out, "JPEG", quality=85)
        return out
    length = media_duration(path) or 0
    t = min(at, max(0.0, length / 2)) if length else 0
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "3", str(out)],
        check=True,
    )  # fmt: skip
    return out


def media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
