"""Stage 3 / test 1 — voice first: does a fixed local voice + LTX audio-to-video keep voices right and lips in sync?

On The Infinity Palette's own lines:
  1. Cast Andie's and Celeste's voices once (Qwen3-TTS VoiceDesign) and clone one line each (Qwen3-TTS Base).
  2. Make each speaker's own close-up keyframe in the studio (OpenAI image edit from their sheet + the studio keyframe).
  3. Animate each speaker's own frame to their exact line with LTX a2v:
       celeste_default — a2v defaults (30 steps, CFG + STG)
       celeste_fast    — 15 steps, no STG pass
       andie_fast      — 15 steps, no STG pass
  4. Put the clean TTS audio back on each clip, and report timing.

Run:  uv run python stage3/01_voice_first.py
"""

import json
import math
import subprocess
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
import soundfile as sf
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
PROD = ROOT / "productions" / "the-infinity-palette"
OUT = PROD / "tests" / "voice_first"
MODEL = ROOT / "models" / "ltx-2.5-mlx-q8"
SR = 24000
FPS = 24
LEAD_S, TAIL_S = 0.3, 0.4

VOICES = {
    "andie_navaro": dict(
        instruct="A warm, clear, low-pitched female voice of a woman in her early thirties, natural American English, grounded and sincere, at a calm pace.",
        ref_text="I mix every shade by hand in my little studio, and when a color finally comes out right, it feels like magic.",
    ),
    "celeste_cartwright": dict(
        instruct="A smooth, measured, cultured female voice of an elegant woman in her late fifties, polished American English, slow and controlled, with quiet authority.",
        ref_text="In this business, darling, ideas are cheap. What matters is who owns them, and who has the patience to wait.",
    ),
}
LINES = {
    "celeste": ("celeste_cartwright", "Clever girl. This could be worth a fortune."),
    "andie": ("andie_navaro", "I built it myself. Every shade, every formula."),
}


def synth(model, seed, **kwargs) -> np.ndarray:
    mx.random.seed(seed)
    return np.concatenate([np.array(r.audio, dtype=np.float32) for r in model.generate(lang_code="english", **kwargs)])


def padded_line(audio: np.ndarray, out: Path) -> tuple[Path, int]:
    """Lead-in and tail silence, then padded to LTX's 8k+1 frame grid (a2v needs audio covering the clip)."""
    seconds = len(audio) / SR + LEAD_S + TAIL_S
    frames = 8 * math.ceil((math.ceil(seconds * FPS) - 1) / 8) + 1
    total = int((frames / FPS + 0.05) * SR)
    lead = np.zeros(int(LEAD_S * SR), dtype=np.float32)
    clip = np.concatenate([lead, audio])
    clip = np.concatenate([clip, np.zeros(max(0, total - len(clip)), dtype=np.float32)])
    sf.write(out, clip, SR, subtype="PCM_16")
    return out, frames


def a2v(name: str, prompt: str, audio: Path, image: Path, frames: int, extra: list[str]) -> float:
    video = OUT / f"{name}.mp4"
    t0 = time.perf_counter()
    cmd = ["uv", "run", "--project", str(ROOT / "ltx-2-mlx"), "ltx-2-mlx", "a2v", "--model", str(MODEL),
           "-p", prompt, "--audio", str(audio), "-i", str(image), "-H", "512", "-W", "768",
           "-f", str(frames), "--frame-rate", str(FPS), "--seed", "42", "--low-ram", "-o", str(video), *extra]  # fmt: skip
    with open(OUT / f"{name}.log", "w") as log:
        subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    seconds = time.perf_counter() - t0
    # The model's audio is a reconstruction: put the clean voice back.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(OUT / f"{name}_final.mp4")], check=True)  # fmt: skip
    print(f"{name}: {seconds / 60:.1f} min", flush=True)
    return seconds


def main() -> None:
    from mlx_audio.tts.utils import load_model

    from storyvid.keyframes import KeyframeArtist, fit_frame
    from storyvid.qa import VoiceScorer, cosine

    (OUT / "voices").mkdir(parents=True, exist_ok=True)
    cast = {c["id"]: c for c in json.loads((PROD / "preprod" / "cast.json").read_text())["characters"]}
    report = {"timings_s": {}}

    # 1. Casting: design each voice once, then clone the line from that reference.
    t0 = time.perf_counter()
    designer = load_model("mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16")
    for cid, v in VOICES.items():
        sf.write(OUT / "voices" / f"{cid}.wav", synth(designer, 7, text=v["ref_text"], instruct=v["instruct"]), SR)
    del designer
    cloner = load_model("mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16")
    lines = {}
    for key, (cid, text) in LINES.items():
        audio = synth(cloner, 7, text=text, ref_audio=str(OUT / "voices" / f"{cid}.wav"), ref_text=VOICES[cid]["ref_text"])
        lines[key] = padded_line(audio, OUT / f"{key}_line.wav")
    report["timings_s"]["casting_and_lines"] = round(time.perf_counter() - t0, 1)
    scorer = VoiceScorer(with_qwen=False)
    report["voice_vs_cast_reference"] = {
        key: round(cosine(scorer.embed(OUT / "voices" / f"{cid}.wav")["resemblyzer"], scorer.embed(lines[key][0])["resemblyzer"]), 3)
        for key, (cid, _) in LINES.items()
    }

    # 2. Celeste's own close-up in the studio (no hard-coded character details).
    kf = json.loads((PROD / "preprod" / "keyframes.json").read_text())
    studio = kf["scenes"]["studio"]
    studio_frame = ROOT / next(c["frame"] for c in studio["candidates"] if c["n"] == studio["chosen"])
    t0 = time.perf_counter()
    raw = KeyframeArtist().edit(
        [PROD / "preprod" / "refs" / "celeste_cartwright_sheet.png", studio_frame],
        "A single frame from a photorealistic live-action film, 3:2 landscape: a medium close-up of the woman from the "
        "character sheet, standing in the makeup studio shown in the second image, same set and the same warm late-afternoon "
        "window light. She holds a makeup palette and looks at it with a cool, calculating half smile, her face turned three "
        "quarters toward the camera, lips closed. She is the only person in frame. Keep her face, hair, age and clothing "
        "identical to the character sheet. No text, captions or watermarks.",
        OUT / "celeste_closeup_raw.png",
    )
    celeste_frame = fit_frame(raw.path, OUT / "celeste_closeup.png")
    report["timings_s"]["celeste_keyframe"] = raw.seconds
    raw = KeyframeArtist().edit(
        [PROD / "preprod" / "refs" / "andie_navaro_sheet.png", studio_frame],
        "A single frame from a photorealistic live-action film, 3:2 landscape: a medium close-up of the woman from the "
        "character sheet in the makeup studio shown in the second image, same set and the same warm late-afternoon window "
        "light. She proudly holds up her makeup palette toward the camera, face toward the camera, lips closed. She is the "
        "only person in frame. Keep her face, hair, age and clothing identical to the character sheet. No text, captions "
        "or watermarks.",
        OUT / "andie_closeup_raw.png",
    )
    andie_frame = fit_frame(raw.path, OUT / "andie_closeup.png")
    report["timings_s"]["andie_keyframe"] = raw.seconds

    # 3. Each speaker's own frame, animated to their exact line.
    setting = "in her bright makeup studio, late afternoon, warm amber window light through sheer curtains"
    celeste_prompt = (f"{cast['celeste_cartwright']['bible']}, {setting}. Medium close-up: she studies the palette in her hands "
                      "with a cool, calculating smile and says, smooth and measured: \"Clever girl. This could be worth a fortune.\" "
                      "Static camera.")  # fmt: skip
    andie_prompt = (f"{cast['andie_navaro']['bible']}, {setting}. She holds up her palette, proud, and says warmly and clearly: "
                    "\"I built it myself. Every shade, every formula.\" Static camera.")  # fmt: skip
    fast = ["--stage1-steps", "15", "--stg-scale", "0"]
    audio, frames = lines["celeste"]
    report["timings_s"]["celeste_default"] = round(a2v("celeste_default", celeste_prompt, audio, celeste_frame, frames, []), 1)
    report["timings_s"]["celeste_fast"] = round(a2v("celeste_fast", celeste_prompt, audio, celeste_frame, frames, fast), 1)
    audio, frames = lines["andie"]
    report["timings_s"]["andie_fast"] = round(a2v("andie_fast", andie_prompt, audio, andie_frame, frames, fast), 1)
    report["frames"] = {k: v[1] for k, v in lines.items()}
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
