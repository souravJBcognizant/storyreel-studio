"""Cut the chosen takes into one film: normalize each clip, fade at scene changes, concatenate."""

from dataclasses import dataclass
from pathlib import Path

from .media import duration, ffmpeg

MIN_AUDIO_FADE = 0.04  # always fade a little so cuts never click


@dataclass
class Clip:
    path: Path
    trim_start: float = 0.0  # continued shots repeat the previous shot's last frame — drop it
    fade_in: float = 0.0
    fade_out: float = 0.0


def _normalize(clip: Clip, out: Path, fps: int, width: int, height: int) -> Path:
    length = duration(clip.path) - clip.trim_start
    vf = [f"trim=start={clip.trim_start:.4f}", "setpts=PTS-STARTPTS", f"fps={fps}", f"scale={width}:{height}"]
    if clip.fade_in:
        vf.append(f"fade=t=in:st=0:d={clip.fade_in}")
    if clip.fade_out:
        vf.append(f"fade=t=out:st={length - clip.fade_out:.4f}:d={clip.fade_out}")
    a_in, a_out = max(clip.fade_in, MIN_AUDIO_FADE), max(clip.fade_out, MIN_AUDIO_FADE)
    af = [
        f"atrim=start={clip.trim_start:.4f}", "asetpts=PTS-STARTPTS",
        "loudnorm=I=-18:TP=-2:LRA=11", "aresample=48000",
        f"afade=t=in:st=0:d={a_in}", f"afade=t=out:st={length - a_out:.4f}:d={a_out}", "apad",
    ]  # fmt: skip
    ffmpeg(
        "-i", str(clip.path), "-vf", ",".join(vf + ["format=yuv420p"]), "-af", ",".join(af),
        "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out),
    )  # fmt: skip
    return out


def assemble(clips: list[Clip], out: Path, work: Path, fps: int, width: int, height: int, comment: str) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    parts = [_normalize(c, work / f"{i:02d}_{c.path.stem}.mp4", fps, width, height) for i, c in enumerate(clips)]
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    partial = out.with_name(f"{out.stem}.partial{out.suffix}")  # an interrupted cut never replaces the last film
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
           "-movflags", "+faststart", "-metadata", f"comment={comment}", str(partial))  # fmt: skip
    partial.replace(out)
    return out
