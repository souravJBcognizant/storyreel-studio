"""Voice audition: render the main character's first lines so the producer can approve the voice.

LTX invents a voice from the voice phrase, so a new character has no voice reference until someone
approves one. The audition renders up to three planned lines, each anchored on its scene's keyframe,
checks the words and how alike the voices are, and waits for approval. Approved clips become the
character's voice_refs, the reference every later line is checked against.

Run:  python -m storyvid.audition <production_id>
"""

import itertools
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from .events import EventLog
from .media import Renderer, extract_audio, frames_for
from .plan import build_prompt, load_plan
from .qa import VoiceScorer, cosine, word_error_rate

PROJECT = Path(__file__).resolve().parents[1]
PRODUCTIONS = PROJECT / "productions"
MAX_LINES = 3
SEED = 1234
WORDS_PER_SECOND = 2.6  # unhurried speech
PADDING_S = 1.2  # breath before and after the line
MAX_AUDITION_S = 5.0  # a voice reference needs a few seconds of speech, not the whole shot


def _plan_path(pid: str) -> Path:
    prod = json.loads((PRODUCTIONS / pid / "production.json").read_text())
    return PROJECT / prod["plan"]


def run(pid: str) -> dict:
    from mlx_audio.stt.utils import load_model

    from .api import store
    from .pipeline import MODEL_DIR, RUNTIME_DIR, STT_MODEL

    out = PRODUCTIONS / pid / "preprod" / "voice"
    out.mkdir(parents=True, exist_ok=True)
    events = EventLog(out)
    plan = load_plan(_plan_path(pid))
    speakers = Counter(s.character for s in plan.shots() if s.line)
    if not speakers:
        raise ValueError("the plan has no lines to audition")
    character = speakers.most_common(1)[0][0]
    # One line per scene first, so the audition hears the voice in different settings.
    lines, seen = [], set()
    for shot in [s for s in plan.shots() if s.line and s.character == character]:
        if shot.scene_id not in seen:
            lines.append(shot)
            seen.add(shot.scene_id)
    lines += [s for s in plan.shots() if s.line and s.character == character and s not in lines]
    lines = lines[:MAX_LINES]
    events.emit("run_started", character=character, shots=[{"id": s.id, "scene": s.scene_id, "takes": 1} for s in lines])
    events.emit("phase", name="rendering")

    renderer = Renderer(PROJECT, MODEL_DIR, RUNTIME_DIR, plan.width, plan.height, plan.fps)
    stt = load_model(STT_MODEL)
    voices = VoiceScorer(with_qwen=False)
    clips, embs = [], {}
    for shot in lines:
        anchor = plan.scene(shot.scene_id).shots[0].image
        video = out / f"{shot.id}.mp4"
        events.emit("take_started", shot=shot.id, take=0, seed=SEED, cached=video.exists())
        # Sized to the line: left to itself the duration predictor picks up to 8 s, and cost grows
        # faster than length (an 8 s clip costs about 3.5x a 4 s one).
        seconds = min(len(shot.line.split()) / WORDS_PER_SECOND + PADDING_S, MAX_AUDITION_S)
        result = renderer.render(build_prompt(plan, shot), video, SEED, frames_for(max(seconds, 3.0), plan.fps), anchor)
        wav = extract_audio(video, video.with_suffix(".wav"))
        heard = stt.generate(str(wav), language="en").text.strip()
        embs[shot.id] = voices.embed(wav)["resemblyzer"]
        clip = {"shot": shot.id, "scene": shot.scene_id, "line": shot.line, "heard": heard,
                "wer": round(word_error_rate(shot.line, heard), 3), "render_s": round(result.seconds, 1),
                "video": str(video.relative_to(PROJECT)), "audio": str(wav.relative_to(PROJECT))}  # fmt: skip
        clips.append(clip)
        events.emit("take_done", shot=shot.id, index=0, passed=clip["wer"] <= 0.2, wer=clip["wer"],
                    render_s=clip["render_s"], cached=result.cached, failures=[], voice=None,
                    identity=None, continuity=None)  # fmt: skip
        events.emit("shot_done", shot=shot.id, chosen=0, takes=1, needs_review=clip["wer"] > 0.2)
        print(f"{time.strftime('%H:%M:%S')} [{shot.id}] {clip['render_s']}s heard {heard!r}", flush=True)
    pairs = [round(cosine(embs[a], embs[b]), 3) for a, b in itertools.combinations(embs, 2)]
    report = {"character": character, "clips": clips, "consistency": min(pairs) if pairs else None, "pairs": pairs}
    (PRODUCTIONS / pid / "preprod" / "voice.json").write_text(json.dumps(report, indent=2))
    store.set_step(pid, "voice", "awaiting_approval")
    events.emit("run_finished", consistency=report["consistency"])
    return report


def adopt_voice(pid: str) -> None:
    """Write the approved audition clips into the plan as the character's voice reference."""
    report = json.loads((PRODUCTIONS / pid / "preprod" / "voice.json").read_text())
    plan_file = _plan_path(pid)
    plan = json.loads(plan_file.read_text())
    plan["characters"][report["character"]]["voice_refs"] = [
        os.path.relpath(PROJECT / c["audio"], plan_file.parent) for c in report["clips"] if c["wer"] <= 0.2
    ]
    plan_file.write_text(json.dumps(plan, indent=2))
    load_plan(plan_file)  # still valid


if __name__ == "__main__":
    out_dir = PRODUCTIONS / sys.argv[1] / "preprod" / "voice"
    try:
        print(json.dumps(run(sys.argv[1]), indent=2))
    except Exception as exc:
        out_dir.mkdir(parents=True, exist_ok=True)
        EventLog(out_dir).emit("run_failed", error=f"{type(exc).__name__}: {exc}")
        raise
