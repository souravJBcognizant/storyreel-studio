"""Dubbing: every line in the character's cast voice, timed to the performance LTX rendered.

Use the original recording as the timing reference. Measure speech onsets and pauses in both
recordings, then align words inside each phrase with continuous, pitch-preserving time stretching.
Only phrase boundaries are cut; individual words are never rendered as independent audio pieces.
Off-camera lines keep their natural timing.

Qwen3-TTS (Base) clones every line from the character's cast voice; Whisper supplies the word timings.
"""

import difflib
import hashlib
import json
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
FADE = int(0.006 * SR)  # fade only the outer edges of a complete line
DUB_VERSION = 3  # align to the original audio, including its lead-in and phrase pauses
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
    alignment: list[dict]  # phrase spans and word timing anchors in the original and overlay
    words_found: int


class DubError(RuntimeError):
    pass


class Dubber:
    def __init__(self, stt, cache: Path):
        self.stt = stt
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self._tts = None
        self._timings: dict[tuple[Path, str], list] = {}

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

    def directed_line(self, voice_description: str, line: str, direction: str) -> Path:
        """Generate an alternate delivery from a human direction without changing the words."""
        key = hashlib.sha1(f"{voice_description}|{line}|{direction}".encode()).hexdigest()[:12]
        out = self.cache / f"directed_{key}.wav"
        if out.exists():
            return out
        from .casting import Casting

        prompt = f"{voice_description.strip()}. Delivery direction: {direction.strip()}"
        seed = SEED + int(key[:8], 16) % 100_000
        return Casting().design(prompt, line, out, seed=seed)

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

    def timings(self, audio: Path) -> list:
        """Word timings cached by recording contents, shared across takes and later exports."""
        digest = hashlib.sha1(audio.read_bytes()).hexdigest()
        key = (audio, digest)
        if key in self._timings:
            return self._timings[key]
        path = audio.with_suffix(".timing.json")
        try:
            saved = json.loads(path.read_text())
        except (OSError, ValueError):
            saved = {}
        if saved.get("sha1") == digest and saved.get("version") == 1:
            result = saved["words"]
        else:
            if self.stt is None:
                from mlx_audio.stt.utils import load_model

                self.stt = load_model("mlx-community/whisper-large-v3-turbo-asr-fp16")
            result = listen(self.stt, audio)[1]
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"sha1": digest, "version": 1, "words": result}))
            tmp.replace(path)
        self._timings[key] = result
        return result

    def dub(self, performance: list[tuple[str, float, float]], cast_line: Path, line: str,
            length_s: float, *, original_audio: Path) -> Dub:
        """Align the overlay to the words and actual speech activity in the original recording."""
        from .alignment import align

        expected = words(line)
        voice = _read_voice(cast_line)
        original = _read_voice(original_audio)

        def valid(spans, seconds):
            return [span if span is not None and np.all(np.isfinite(span))
                    and 0 <= span[0] < span[1] <= seconds + .1 else None for span in spans]

        target = valid(self._map(expected, performance), length_s)
        if sum(t is not None for t in target) < max(1, int(np.ceil(.7 * len(expected)))):
            raise DubError("not enough usable timings in the original audio")
        source = valid(self._map(expected, self.timings(cast_line)), len(voice) / SR)
        found = sum(s is not None and t is not None for s, t in zip(source, target))
        if found < max(1, int(np.ceil(.7 * len(expected)))):
            raise DubError(f"{found} of {len(expected)} words matched between the recordings")
        try:
            track, alignment = align(voice, original, source, target, length_s)
        except ValueError as exc:
            raise DubError(str(exc)) from exc
        return Dub(track, alignment, found)

    def lay_over(self, cast_line: Path, length_s: float) -> Dub:
        """Off camera: preserve the complete line, shortening the lead-in if space is tight."""
        voice = _read_voice(cast_line)
        natural = len(voice) / SR
        length = min(natural, length_s)
        if length <= 0 or length < natural / MAX_STRETCH:
            raise DubError("the complete cast line cannot fit in this take; use original audio or a longer take")
        start = min(OFF_CAMERA_LEAD_S, max(0.0, length_s - length))
        return Dub(_place(voice, start, length, length_s), [], 0)


def _read_voice(path: Path) -> np.ndarray:
    voice, sr = sf.read(path, dtype="float32")
    if sr != SR or voice.ndim != 1:
        raise DubError(f"cast line must be {SR} Hz mono")
    if not len(voice) or not np.all(np.isfinite(voice)):
        raise DubError("cast line is empty or invalid")
    return voice


def _place(voice: np.ndarray, start: float, length: float, total: float) -> np.ndarray:
    track = np.zeros(int(round(total * SR)), dtype=np.float32)
    piece = _stretch(voice, length)
    a = int(round(start * SR))
    n = min(len(piece), len(track) - a)
    track[a:a + n] = piece[:n]
    return track


def _stretch(segment: np.ndarray, target_s: float) -> np.ndarray:
    """Time-stretch to target_s seconds without changing pitch (ffmpeg atempo, chained for big ratios)."""
    want = int(round(max(target_s, 0) * SR))
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
    if abs(want - len(segment)) <= 1:
        out = segment.copy()  # no tempo processing when the natural timing already fits
    else:
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "in.wav", Path(d) / "out.wav"
            # atempo needs look-ahead at EOF. Supply silence beyond the last phoneme so its buffered
            # tail is flushed, then trim the silence, rather than losing the end of the sentence.
            padded = np.pad(segment, (0, int(0.15 * SR)))
            sf.write(src, padded, SR, subtype="FLOAT")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", ",".join(filters),
                            "-ar", str(SR), "-c:a", "pcm_f32le", str(dst)], check=True)
            out, _ = sf.read(dst, dtype="float32")
    out = out[:want] if len(out) >= want else np.pad(out, (0, want - len(out)))
    if len(out) > 2 * FADE:
        ramp = np.linspace(0, 1, FADE, dtype=np.float32)
        out[:FADE] *= ramp
        out[-FADE:] *= ramp[::-1]
    return out
