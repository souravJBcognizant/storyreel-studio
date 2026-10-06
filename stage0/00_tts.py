"""Stage 0 / test 1 — can Qwen3-TTS keep one character's voice consistent?

1. The VoiceDesign model invents the character's voice from a text description
   and speaks a reference line -> voice_ref.wav (+ its transcript).
2. The Base model clones that reference for three lines with different emotions.
3. Two controls calibrate the scores:
     - "redesign": the SAME description re-designed with another seed
       (shows why we clone from a fixed reference instead of re-designing per line)
     - "other_voice": a deliberately different voice (negative control)
4. Every clip is scored against the reference with two speaker encoders:
     - resemblyzer (GE2E, independent of the TTS model)
     - Qwen3-TTS's own speaker encoder (the one cloning conditions on)

Run:  uv run python stage0/00_tts.py
"""

import json
import subprocess
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load_model
from storyvid.qa import VoiceScorer

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out" / "tts"
SR = 24000
SEED = 1234

VOICE_DESIGN_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"
CLONE_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"

CHARACTER_VOICE = (
    "A bright, warm young adult male voice, mid-pitch, friendly and curious, "
    "clear American English, moderate pace, slightly playful."
)
REF_TEXT = (
    "Hi, I'm Elio. I build little machines out of the junk that washes up on the beach, "
    "and today I think I've finally made one that can fly."
)
OTHER_VOICE = "A slow, deep, raspy elderly woman's voice with a British accent, calm and stern."

# Emotion comes from the words and punctuation only — the voice settings never change.
LINES = {
    "line1_nervous": "Okay, okay... deep breath. This is it. Three, two, one!",
    "line2_excited": "It works! It actually works! Look at it go!",
    "line3_worried": "Wait, no, no, no! Come back here, please!",
}


def synth(model, seed, **kwargs) -> tuple[np.ndarray, float, float]:
    """Generate one utterance; returns (audio, seconds_taken, peak_gb)."""
    mx.random.seed(seed)
    mx.reset_peak_memory()
    t0 = time.perf_counter()
    chunks = [np.array(r.audio, dtype=np.float32) for r in model.generate(lang_code="english", **kwargs)]
    secs = time.perf_counter() - t0
    return np.concatenate(chunks), secs, mx.get_peak_memory() / 1e9


def normalize(raw: Path, dst: Path) -> None:
    """Loudness-normalize to -16 LUFS, mono, 24 kHz, 16-bit — the format LTX a2v expects."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "1", "-ar", str(SR), "-sample_fmt", "s16", str(dst)],
        check=True,
    )


def save(name: str, audio: np.ndarray) -> Path:
    raw = OUT / f"{name}.raw.wav"
    dst = OUT / f"{name}.wav"
    sf.write(raw, audio, SR)
    normalize(raw, dst)
    raw.unlink()
    return dst


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    timings = {}

    # 1. Design the character voice once.
    t0 = time.perf_counter()
    designer = load_model(VOICE_DESIGN_MODEL)
    timings["load_voice_design_s"] = round(time.perf_counter() - t0, 1)

    audio, secs, peak = synth(designer, SEED, text=REF_TEXT, instruct=CHARACTER_VOICE)
    ref_path = save("voice_ref", audio)
    (OUT / "voice_ref.txt").write_text(REF_TEXT)
    timings["voice_ref"] = {"gen_s": round(secs, 1), "audio_s": round(len(audio) / SR, 1), "peak_gb": round(peak, 2)}

    # Controls, made with the designer while it is loaded.
    audio, secs, peak = synth(designer, SEED + 1, text=LINES["line1_nervous"], instruct=CHARACTER_VOICE)
    save("control_redesign", audio)
    timings["control_redesign"] = {"gen_s": round(secs, 1), "audio_s": round(len(audio) / SR, 1), "peak_gb": round(peak, 2)}

    audio, secs, peak = synth(designer, SEED, text=LINES["line2_excited"], instruct=OTHER_VOICE)
    save("control_other_voice", audio)
    timings["control_other_voice"] = {"gen_s": round(secs, 1), "audio_s": round(len(audio) / SR, 1), "peak_gb": round(peak, 2)}
    del designer
    mx.clear_cache()

    # 2. Clone the reference for every line (same file, same seed, same settings).
    t0 = time.perf_counter()
    cloner = load_model(CLONE_MODEL)
    timings["load_clone_s"] = round(time.perf_counter() - t0, 1)

    for name, text in LINES.items():
        audio, secs, peak = synth(cloner, SEED, text=text, ref_audio=str(ref_path), ref_text=REF_TEXT)
        save(name, audio)
        timings[name] = {"gen_s": round(secs, 1), "audio_s": round(len(audio) / SR, 1), "peak_gb": round(peak, 2)}

    report = {"models": [VOICE_DESIGN_MODEL, CLONE_MODEL], "seed": SEED, "timings": timings}
    (OUT / "report.json").write_text(json.dumps(report, indent=2))

    # 3. Score every clip against the reference.
    clips = [OUT / f"{name}.wav" for name in [*LINES, "control_redesign", "control_other_voice"]]
    report["similarity_to_ref"] = VoiceScorer(qwen_model=cloner).score(ref_path, clips)
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
