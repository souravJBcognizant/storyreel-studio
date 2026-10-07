"""Dubbing: every line in the character's cast voice, timed to the performance LTX rendered.

LTX animates the mouth to the speech it generates itself, so the voice can't simply be swapped: a
different recording drifts out of sync. But the cast voice says the same words. Each of its words is
placed where LTX's character says that word, and stretched by at most ±30% to fit, so the mouth shapes
line up while the voice is the same in every shot. Off-camera lines skip the alignment and are laid over
the picture after a short lead-in.

Qwen3-TTS (Base) clones every line from the character's cast voice; Whisper supplies the word timings.
"""

import difflib
import hashlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 24000
CLONE_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
MAX_STRETCH = 1.3  # beyond about ±30% stretched speech sounds slowed down or sped up
FADE = int(0.006 * SR)  # 6 ms fades so stitched words never click
OFF_CAMERA_LEAD_S = 0.35
SEED = 7


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def listen(stt, audio: Path) -> tuple[str, list[tuple[str, float, float]]]:
    """One Whisper pass: the transcript, and each word with its start and end in seconds."""
    result = stt.generate(str(audio), language="en", word_timestamps=True)
    heard = []
    for seg in result.segments:
        for w in seg.get("words", []):
            token = "".join(words(w["word"]))
            if token:
                heard.append((token, float(w["start"]), float(w["end"])))
    return result.text.strip(), heard


@dataclass
class Dub:
    track: np.ndarray  # the voice on the take's timeline (SR, mono)
    alignment: list[dict]  # per word: where LTX said it, where the cast voice was placed, stretch
    words_found: int


class DubError(RuntimeError):
    pass


class Dubber:
    def __init__(self, stt, cache: Path):
        self.stt = stt
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self._tts = None
        self._timings: dict[Path, list[tuple[str, float, float]]] = {}

    # ------------------------------------------------------------ cast voice lines

    def cast_line(self, voice: Path, voice_text: str, line: str) -> Path:
        """The line in the cast voice, generated once per (voice, line) and cached."""
        key = hashlib.sha1(Path(voice).read_bytes() + f"|{voice_text}|{line}|{SEED}".encode()).hexdigest()[:12]
        out = self.cache / f"line_{key}.wav"
        if out.exists():
            return out
        import mlx.core as mx

        if self._tts is None:
            from mlx_audio.tts.utils import load_model

            self._tts = load_model(CLONE_MODEL)
        mx.random.seed(SEED)
        audio = np.concatenate([np.array(r.audio, dtype=np.float32) for r in self._tts.generate(
            text=line, ref_audio=str(voice), ref_text=voice_text, lang_code="english")])  # fmt: skip
        nz = np.nonzero(np.abs(audio) > 1e-4)[0]
        sf.write(out, audio[nz[0]: nz[-1] + 1] if len(nz) else audio, SR)
        return out

    # ------------------------------------------------------------ timing

    @staticmethod
    def _map(expected: list[str], heard: list[tuple[str, float, float]]) -> list[tuple[float, float] | None]:
        """Timing for each expected word from a transcript that may differ slightly (e.g. a misheard name)."""
        spans: list[tuple[float, float] | None] = [None] * len(expected)
        ops = difflib.SequenceMatcher(a=expected, b=[w for w, *_ in heard], autojunk=False).get_opcodes()
        for tag, a0, a1, b0, b1 in ops:
            if tag in ("equal", "replace") and (a1 - a0) == (b1 - b0):
                for i, j in zip(range(a0, a1), range(b0, b1)):
                    spans[i] = (heard[j][1], heard[j][2])
            elif tag == "replace" and b1 > b0:  # unequal block: share its time out evenly
                t0, t1 = heard[b0][1], heard[b1 - 1][2]
                step = (t1 - t0) / (a1 - a0)
                for k, i in enumerate(range(a0, a1)):
                    spans[i] = (t0 + k * step, t0 + (k + 1) * step)
        return spans

    # ------------------------------------------------------------ the dub

    def dub(self, performance: list[tuple[str, float, float]], cast_line: Path, line: str, length_s: float) -> Dub:
        """The cast line re-timed to the performance's words (from `listen`), on a track of length_s seconds."""
        expected = words(line)
        if cast_line not in self._timings:
            self._timings[cast_line] = listen(self.stt, cast_line)[1]
        target = self._map(expected, performance)
        source = self._map(expected, self._timings[cast_line])
        voice, sr = sf.read(cast_line, dtype="float32")
        if sr != SR:
            raise DubError(f"cast line must be {SR} Hz")
        track = np.zeros(int(length_s * SR), dtype=np.float32)
        found = sum(1 for t, s in zip(target, source) if t and s)
        if found < max(1, int(0.7 * len(expected))):
            raise DubError(f"{found} of {len(expected)} words matched")
        alignment = []
        first = True
        for word, t, s in zip(expected, target, source):
            if not (t and s):
                continue
            (t0, t1), (s0, s1) = t, s
            natural = s1 - s0
            length = min(max(t1 - t0, natural / MAX_STRETCH), natural * MAX_STRETCH)
            # Whisper word spans often include the pause before a word; the first word usually carries the
            # lead-in, so it lines up with the end of its span and the rest line up with their starts.
            # (When the performance starts speaking at once, that can fall before the clip: start at 0.)
            start_s = max(0.0, t1 - length) if first else t0
            first = False
            piece = _stretch(voice[int(s0 * SR): int(s1 * SR)], length)
            a = int(start_s * SR)
            n = max(0, min(len(piece), len(track) - a))
            track[a: a + n] += piece[:n]
            alignment.append({"word": word, "said": [round(t0, 2), round(t1, 2)], "placed": [round(start_s, 2), round(start_s + length, 2)],
                              "stretch": round(natural / max(length, 1e-3), 2)})  # fmt: skip
        return Dub(np.clip(track, -1, 1), alignment, found)

    def lay_over(self, cast_line: Path, length_s: float) -> Dub:
        """Off camera: the cast line as spoken, after a short lead-in."""
        voice, _ = sf.read(cast_line, dtype="float32")
        track = np.zeros(int(length_s * SR), dtype=np.float32)
        a = int(OFF_CAMERA_LEAD_S * SR)
        n = max(0, min(len(voice), len(track) - a))
        track[a: a + n] = voice[:n]
        return Dub(track, [], 0)


def _stretch(segment: np.ndarray, target_s: float) -> np.ndarray:
    """Time-stretch to target_s seconds without changing pitch (ffmpeg atempo, chained for big ratios)."""
    want = int(max(target_s, 0) * SR)
    if len(segment) < 32 or want == 0:
        return np.zeros(want, dtype=np.float32)
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
    out = out[:want] if len(out) >= want else np.concatenate([out, np.zeros(want - len(out), dtype=np.float32)])
    if len(out) > 2 * FADE:
        ramp = np.linspace(0, 1, FADE, dtype=np.float32)
        out[:FADE] *= ramp
        out[-FADE:] *= ramp[::-1]
    return out
