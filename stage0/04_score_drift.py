"""Stage 0 / test 5 scoring — does LTX's Elio voice hold across different scenes and seeds?

Reference = the average voice of the three beach takes from test 4 (provisional "LTX Elio").
For each new shot: Whisper word error rate, and resemblyzer similarity to that reference.
For calibration, test 4's beach takes are scored against the same reference.

Run:  uv run python stage0/04_score_drift.py
"""

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from mlx_audio.stt.utils import load_model
from storyvid.qa import VoiceScorer, cosine, word_error_rate

ROOT = Path(__file__).resolve().parent
LTX = ROOT / "out" / "ltx"
DRIFT = LTX / "drift"
STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
BEACH_TAKES = ["joint_line1_nervous", "joint_line2_excited", "joint_line3_worried"]

LINES = {
    "workshop": "If I tighten this spring just a little more... there. Perfect.",
    "rain": "Come on, come on, the bus is leaving without me!",
    "hill": "One day, everyone in this town is going to look up and see my machines flying.",
    "frustrated": "Why won't you fly? I followed every single step!",
}


def main() -> None:
    stt = load_model(STT_MODEL)
    scorer = VoiceScorer(with_qwen=False)

    beach = {n: scorer.embed(LTX / f"{n}.wav")["resemblyzer"] for n in BEACH_TAKES}
    ref = np.mean([e / np.linalg.norm(e) for e in beach.values()], axis=0)

    report = {"beach_takes_vs_ref": {n: round(cosine(ref, e), 3) for n, e in beach.items()}, "shots": {}}
    for name, line in LINES.items():
        path = DRIFT / f"{name}.wav"
        heard = stt.generate(str(path), language="en").text.strip()
        report["shots"][name] = {
            "seconds": round(sf.info(path).duration, 2),
            "heard": heard,
            "wer": round(word_error_rate(line, heard), 2),
            "sim_to_ltx_elio": round(cosine(ref, scorer.embed(path)["resemblyzer"]), 3),
        }

    (DRIFT / "drift_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
