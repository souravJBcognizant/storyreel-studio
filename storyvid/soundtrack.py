"""The film's soundtrack, built once for the whole cut rather than clip by clip.

Dubbed films: LTX's audio of an on-camera line holds LTX's own voice, so under those shots the scene's
ambience plays instead, looped from one of its silent shots and crossfaded in and out at the cuts. Every
other shot keeps its own LTX sound, which is in sync with its picture (a door, a gust, an explosion),
levelled to within a few dB of the scene's ambience so the cuts don't jump. Each line is placed in the
cast voice at its film time, at LTX's speaking level. Films made before dubbing keep every take's audio.
One loudness pass with a fixed gain then sets the level of the whole film.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 48000
VOICE_DB = -18.5  # LTX speaks at about this level (louder half of its speech frames, -15 to -21 dBFS)
BED_HEADROOM_DB = 12.0  # the ambience under a line stays at least this far below the voice
NATIVE_RANGE_DB = 6.0  # a shot's own sound is kept within this of its scene's ambience
LOOP_FADE_S = 0.6
SWAP_S = 0.15  # crossfade between a shot's own sound and the ambience bed
SCENE_FADE_S = 0.4
MIN_FADE_S = 0.04  # every cut gets at least this, so cuts never click


@dataclass
class Placed:
    scene: str
    take: Path  # the LTX take
    start: float  # where the shot starts in the film, seconds
    length: float  # how long it runs in the film
    trim: float  # seconds cut from the start of the take
    fade_in: float = 0.0
    fade_out: float = 0.0
    voice: np.ndarray | None = None  # dubbed or laid-over line on the take's timeline, 24 kHz mono
    native: bool = True  # dubbed films: keep this shot's own sound (False: it holds LTX's voice)
    bed_source: bool = False  # this shot's sound becomes its scene's ambience


def decode(path: Path) -> np.ndarray:
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "a.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), str(wav)], check=True)
        audio, _ = sf.read(wav, dtype="float32")
    return audio


def level_db(x: np.ndarray) -> float | None:
    """Level of the louder half of the non-silent 20 ms frames: speech level for a voice, typical level for
    ambience. None for silence."""
    n = int(0.02 * SR)
    k = len(x) // n
    if k == 0:
        return None
    e = np.sqrt(np.mean(x[: k * n].reshape(k, n) ** 2, axis=1))
    e = np.sort(e[e > 1e-4])
    return float(20 * np.log10(np.sqrt(np.mean(e[len(e) // 2:] ** 2)))) if len(e) else None


def _gain(db: float) -> float:
    return float(10 ** (db / 20))


def _loop(source: np.ndarray, n: int) -> np.ndarray:
    """Repeat a short recording to n samples, crossfading each join."""
    fade = int(LOOP_FADE_S * SR)
    if len(source) <= 2 * fade:
        return np.resize(source, n)
    out = source.copy()
    ramp = np.linspace(0, 1, fade, dtype=np.float32)
    while len(out) < n:
        out[-fade:] = out[-fade:] * ramp[::-1] + source[:fade] * ramp
        out = np.concatenate([out, source[fade:]])
    return out[:n]


def _fade(x: np.ndarray, fade_in: float, fade_out: float) -> np.ndarray:
    a, b = min(int(fade_in * SR), len(x)), min(int(fade_out * SR), len(x))
    if a:
        x[:a] *= np.linspace(0, 1, a, dtype=np.float32)
    if b:
        x[len(x) - b:] *= np.linspace(1, 0, b, dtype=np.float32)
    return x


def _smooth(mask: np.ndarray, seconds: float) -> np.ndarray:
    """Moving average: turns the on/off edges of a mask into ramps `seconds` long, centred on the edge."""
    n = max(1, int(seconds * SR))
    c = np.concatenate([[0.0], np.cumsum(np.pad(mask, (n // 2, n - n // 2), mode="edge"), dtype=np.float64)])
    return ((c[n:] - c[:-n]) / n)[: len(mask)].astype(np.float32)


def _add(mix: np.ndarray, x: np.ndarray, at: float) -> None:
    s = int(round(at * SR))
    n = max(0, min(len(x), len(mix) - s))
    mix[s: s + n] += x[:n]


def _own_sound(p: Placed) -> np.ndarray:
    return decode(p.take)[int(p.trim * SR): int((p.trim + p.length) * SR)]


def build(cut: list[Placed], dubbed: bool, out: Path) -> Path:
    total = cut[-1].start + cut[-1].length
    mix = np.zeros(int(round(total * SR)), dtype=np.float32)
    if not dubbed:
        for p in cut:
            _add(mix, _fade(_own_sound(p), max(p.fade_in, MIN_FADE_S), max(p.fade_out, MIN_FADE_S)), p.start)
    else:
        scenes = list(dict.fromkeys(p.scene for p in cut))
        for i, scene in enumerate(scenes):
            _scene(mix, [p for p in cut if p.scene == scene], last=i == len(scenes) - 1)
        _fade(mix, max(cut[0].fade_in, MIN_FADE_S), max(cut[-1].fade_out, MIN_FADE_S))
    with tempfile.TemporaryDirectory() as d:
        raw = Path(d) / "mix.wav"
        sf.write(raw, np.clip(mix, -1, 1), SR)
        loudnorm(raw, out)
    return out


def _scene(mix: np.ndarray, shots: list[Placed], last: bool) -> None:
    begin, end = shots[0].start, shots[-1].start + shots[-1].length
    source = next((p for p in shots if p.bed_source), None)
    ref_db = None
    if source is not None:
        raw = decode(source.take)[int(0.1 * SR): -int(0.1 * SR)]
        ref_db = level_db(raw)
    if ref_db is not None and any(not p.native for p in shots):
        bed_db = min(ref_db, VOICE_DB - BED_HEADROOM_DB)
        # The bed runs past the scene's last frame when it ends on a line, fading out under the next scene.
        overlap = SCENE_FADE_S if not (last or shots[-1].native) else 0.0
        n = int(round((end - begin + overlap) * SR))
        bed = _loop(raw * _gain(bed_db - ref_db), n)
        mask = np.zeros(n, dtype=np.float32)
        for p in shots:
            if not p.native:
                a, b = int(round((p.start - begin) * SR)), int(round((p.start + p.length - begin) * SR))
                mask[a: b if p is not shots[-1] else n] = 1.0
        mask = _smooth(mask, SWAP_S)
        lead = SCENE_FADE_S if not shots[0].native else 0.0
        _add(mix, _fade(bed * np.sqrt(mask), lead, SCENE_FADE_S if overlap else 0.0), begin)
    for p in shots:
        if p.native:
            own = _own_sound(p)
            db = level_db(own)
            if ref_db is not None and db is not None:  # pull it to within NATIVE_RANGE_DB of the scene's ambience
                own = own * _gain(min(max(db, ref_db - NATIVE_RANGE_DB), ref_db + NATIVE_RANGE_DB) - db)
            _add(mix, _fade(own, max(p.fade_in, MIN_FADE_S), max(p.fade_out, MIN_FADE_S)), p.start)
        if p.voice is not None:
            v = resample_poly(p.voice, 2, 1).astype(np.float32)[int(p.trim * SR):][: int(p.length * SR)]  # 24 → 48 kHz
            db = level_db(v)
            _add(mix, v * _gain(VOICE_DB - db) if db is not None else v, p.start)


def loudnorm(src: Path, dst: Path, target: str = "I=-16:TP=-1.5:LRA=11") -> Path:
    """Two-pass EBU R128 normalization with one fixed gain (single-pass loudnorm rides the gain, which
    lifts the ambience in quiet stretches), to 48 kHz stereo."""
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, check=True).stderr  # fmt: skip
    m = json.loads(probe[probe.rindex("{"): probe.rindex("}") + 1])
    measured = (f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")  # fmt: skip
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", f"loudnorm={target}:{measured}",
                    "-ar", str(SR), "-ac", "2", str(dst)], check=True)  # fmt: skip
    return dst
