"""Stage 3 / test 2 — dub LTX's own lip-synced performance with the character's fixed local voice.

LTX animates the mouth to the speech it generates, so a different recording laid on top drifts out of
sync. But the cast voice says the *same words*: stretch each of its words to the moment LTX's character
says that word, and the mouth shapes line up again.

  1. Whisper word timestamps on the LTX take and on the cast-voice line (Qwen3-TTS clone).
  2. Stretch every cast-voice word to its LTX counterpart's span (ffmpeg atempo, pitch kept); silences follow LTX.
  3. Put the dubbed voice on the picture.

Run:  uv run python stage3/02_dub.py <ltx_take.mp4> <cast_line.wav> "<line>" <out.mp4>
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 24000
FADE = int(0.006 * SR)  # 6 ms fades so stitched words never click
MAX_STRETCH = 1.3  # beyond about ±30% stretched speech starts to sound slowed down or sped up


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def word_times(stt, audio: Path) -> list[tuple[str, float, float]]:
    result = stt.generate(str(audio), language="en", word_timestamps=True)
    out = []
    for seg in result.segments:
        for w in seg.get("words", []):
            token = "".join(words(w["word"]))
            if token:
                out.append((token, float(w["start"]), float(w["end"])))
    return out


def stretch(segment: np.ndarray, target_s: float) -> np.ndarray:
    """Time-stretch to target_s seconds without changing pitch (ffmpeg atempo, chained for big ratios)."""
    if len(segment) < 32 or target_s <= 0:
        return np.zeros(int(max(target_s, 0) * SR), dtype=np.float32)
    ratio = (len(segment) / SR) / target_s
    filters = []
    while ratio > 2.0:
        filters.append("atempo=2.0")
        ratio /= 2.0
    while ratio < 0.5:
        filters.append("atempo=0.5")
        ratio /= 0.5
    filters.append(f"atempo={ratio:.5f}")
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.wav", Path(d) / "out.wav"
        sf.write(src, segment, SR)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", ",".join(filters), "-ar", str(SR), str(dst)], check=True)
        out, _ = sf.read(dst, dtype="float32")
    want = int(target_s * SR)
    out = out[:want] if len(out) >= want else np.concatenate([out, np.zeros(want - len(out), dtype=np.float32)])
    if len(out) > 2 * FADE:
        ramp = np.linspace(0, 1, FADE, dtype=np.float32)
        out[:FADE] *= ramp
        out[-FADE:] *= ramp[::-1]
    return out


def dub(take: Path, cast_line: Path, line: str, out: Path) -> dict:
    from mlx_audio.stt.utils import load_model

    stt = load_model("mlx-community/whisper-large-v3-turbo-asr-fp16")
    with tempfile.TemporaryDirectory() as d:
        ltx_wav = Path(d) / "ltx.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(take), "-vn", "-ac", "1", "-ar", str(SR), str(ltx_wav)], check=True)
        ltx_audio, _ = sf.read(ltx_wav, dtype="float32")
        target = word_times(stt, ltx_wav)
    voice, sr = sf.read(cast_line, dtype="float32")
    assert sr == SR, f"cast line must be {SR} Hz"
    source = word_times(stt, cast_line)
    expected = words(line)
    if [w for w, *_ in target] != expected or [w for w, *_ in source] != expected:
        raise ValueError(f"word mismatch: LTX said {[w for w, *_ in target]}, cast voice said {[w for w, *_ in source]}, line is {expected}")

    track = np.zeros(len(ltx_audio), dtype=np.float32)
    shifts = []
    for i, ((word, t0, t1), (_, s0, s1)) in enumerate(zip(target, source)):
        # Whisper word spans often include the pause around a word, so never stretch more than MAX_STRETCH:
        # the word keeps a natural length and the rest of the span stays silent. The first word lines up
        # with the end of its span (its span usually starts with the lead-in), the others with the start.
        natural = s1 - s0
        length = min(max(t1 - t0, natural / MAX_STRETCH), natural * MAX_STRETCH)
        start_s = t1 - length if i == 0 else t0
        piece = stretch(voice[int(s0 * SR):int(s1 * SR)], length)
        start = int(start_s * SR)
        track[start:start + len(piece)] += piece[: max(0, len(track) - start)]
        shifts.append({"word": word, "ltx": [round(t0, 2), round(t1, 2)], "placed": [round(start_s, 2), round(start_s + length, 2)],
                       "stretch": round(natural / max(length, 1e-3), 2)})  # fmt: skip
    with tempfile.TemporaryDirectory() as d:
        voice_wav = Path(d) / "voice.wav"
        sf.write(voice_wav, track, SR)
        sf.write(out.with_suffix(".voice.wav"), track, SR)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(take), "-i", str(voice_wav), "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], check=True)  # fmt: skip
    return {"words": shifts, "out": str(out)}


if __name__ == "__main__":
    import json

    take, cast_line, line, out = sys.argv[1:5]
    print(json.dumps(dub(Path(take), Path(cast_line), line, Path(out)), indent=2))
