"""Stage 0 / test 4 scoring — when LTX voices the lines itself:
  - are the words right?             Whisper transcript vs the script (word error rate)
  - is it the same voice every shot? resemblyzer, pairwise across the three shots
  - is it Elio's approved voice?     resemblyzer vs voice_ref.wav
The TTS clones from test 1 get the same three measurements as the baseline.

Run:  uv run python stage0/03_score_joint.py
"""

import itertools
import json
from pathlib import Path

import soundfile as sf
from mlx_audio.stt.utils import load_model
from storyvid.qa import VoiceScorer, cosine, word_error_rate

ROOT = Path(__file__).resolve().parent
TTS = ROOT / "out" / "tts"
LTX = ROOT / "out" / "ltx"
STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"

LINES = {
    "line1_nervous": "Okay, okay... deep breath. This is it. Three, two, one!",
    "line2_excited": "It works! It actually works! Look at it go!",
    "line3_worried": "Wait, no, no, no! Come back here, please!",
}


def main() -> None:
    stt = load_model(STT_MODEL)
    scorer = VoiceScorer(with_qwen=False)
    ref_emb = scorer.embed(TTS / "voice_ref.wav")["resemblyzer"]

    groups = {
        "tts_clone": {name: TTS / f"{name}.wav" for name in LINES},
        "ltx_joint": {name: LTX / f"joint_{name}.wav" for name in LINES},
    }
    report = {}
    for group, clips in groups.items():
        embs, per_clip = {}, {}
        for name, path in clips.items():
            heard = stt.generate(str(path), language="en").text.strip()
            embs[name] = scorer.embed(path)["resemblyzer"]
            per_clip[name] = {
                "seconds": round(sf.info(path).duration, 2),
                "heard": heard,
                "wer": round(word_error_rate(LINES[name], heard), 2),
                "sim_to_elio_ref": round(cosine(ref_emb, embs[name]), 3),
            }
        pairs = {f"{a}~{b}": round(cosine(embs[a], embs[b]), 3) for a, b in itertools.combinations(embs, 2)}
        report[group] = {
            "clips": per_clip,
            "cross_shot_similarity": pairs,
            "cross_shot_min": min(pairs.values()),
        }

    (LTX / "joint_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
