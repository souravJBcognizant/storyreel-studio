"""Cut the chosen takes into one film: normalize each clip's picture, fade at scene changes, concatenate,
and lay the film's soundtrack (storyvid.soundtrack) under it."""

from dataclasses import dataclass
from pathlib import Path

from .media import duration, ffmpeg


@dataclass
class Clip:
    path: Path
    trim_start: float = 0.0  # continued shots repeat the previous shot's last frame — drop it
    fade_in: float = 0.0
    fade_out: float = 0.0
    end: float | None = None  # where the shot ends in the take (None: at the end of the take)


def _normalize(clip: Clip, out: Path, fps: int, width: int, height: int) -> Path:
    end = clip.end if clip.end is not None else duration(clip.path)
    length = end - clip.trim_start
    vf = [f"trim=start={clip.trim_start:.4f}:end={end:.4f}", "setpts=PTS-STARTPTS", f"fps={fps}", f"scale={width}:{height}"]
    if clip.fade_in:
        vf.append(f"fade=t=in:st=0:d={clip.fade_in}")
    if clip.fade_out:
        vf.append(f"fade=t=out:st={length - clip.fade_out:.4f}:d={clip.fade_out}")
    ffmpeg("-i", str(clip.path), "-vf", ",".join(vf + ["format=yuv420p"]), "-an",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out))  # fmt: skip
    return out


def picture(clips: list[Clip], work: Path, fps: int, width: int, height: int) -> list[Path]:
    """Each clip's picture, trimmed, scaled and faded; their durations place the soundtrack."""
    work.mkdir(parents=True, exist_ok=True)
    return [_normalize(c, work / f"{i:02d}_{c.path.stem}.mp4", fps, width, height) for i, c in enumerate(clips)]


def assemble(parts: list[Path], soundtrack: Path, out: Path, work: Path, comment: str) -> Path:
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    partial = out.with_name(f"{out.stem}.partial{out.suffix}")  # an interrupted cut never replaces the last film
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(soundtrack),
           "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", "-metadata", f"comment={comment}", str(partial))  # fmt: skip
    partial.replace(out)
    return out
