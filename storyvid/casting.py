"""Voice casting: every speaking character's voice, designed once from a written description.

Qwen3-TTS VoiceDesign speaks a reference sentence in a voice built from the description; that recording
is the character's cast voice, and every line in the film is cloned from it (storyvid.dub), so a
character sounds the same in every shot. Each new voice is compared with the others already cast
(resemblyzer), so two characters never sound alike. Takes seconds, and the producer approves by ear.
"""

from pathlib import Path

import numpy as np
import soundfile as sf

DESIGN_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"
SR = 24000
SEED = 7
MAX_LIKENESS = 0.80  # resemblyzer: one voice across takes scores 0.85+, different people 0.6-0.75
MIN_SECONDS, MAX_SECONDS = 4.0, 12.0  # a clone needs a few seconds of reference speech


class Casting:
    def __init__(self):
        self._designer = None
        self._scorer = None

    def design(self, description: str, text: str, out: Path, seed: int = SEED) -> Path:
        import mlx.core as mx

        if self._designer is None:
            from mlx_audio.tts.utils import load_model

            self._designer = load_model(DESIGN_MODEL)
        mx.random.seed(seed)
        audio = np.concatenate([np.array(r.audio, dtype=np.float32) for r in self._designer.generate(
            text=text, instruct=description, lang_code="english")])  # fmt: skip
        nz = np.nonzero(np.abs(audio) > 1e-4)[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, audio[nz[0]: nz[-1] + 1] if len(nz) else audio, SR)
        return out

    def likeness(self, voice: Path, others: dict[str, Path]) -> dict[str, float]:
        """How alike `voice` sounds to each of the other cast voices (cosine, 1 = the same voice)."""
        from .qa import VoiceScorer, cosine

        if self._scorer is None:
            self._scorer = VoiceScorer(with_qwen=False)
        mine = self._scorer.embed(voice)["resemblyzer"]
        return {cid: round(cosine(mine, self._scorer.embed(p)["resemblyzer"]), 3) for cid, p in others.items()}


# ------------------------------------------------------------------ a production's cast voices (preprod/voices.json)

_casting: Casting | None = None


def cast_voice(pid: str, cid: str, description: str, text: str) -> dict:
    """Design a new voice candidate for one character; it is chosen if it is distinct and long enough.

    Used by the CastingDirector's CastVoice tool and by a recast from the studio.
    """
    from . import preprod
    from .api import store
    from .media import duration

    global _casting
    cast = preprod.load(pid, "cast")
    if cid not in {c["id"] for c in cast["characters"]}:
        raise ValueError(f"unknown character {cid!r}")
    voices = preprod.load(pid, "voices") or {}
    entry = voices.setdefault(cid, {"candidates": [], "chosen": None})
    n = len(entry["candidates"]) + 1
    out = preprod.folder(pid) / "voices" / f"{cid}_v{n}.wav"
    store.set_step(pid, "voice", "running")
    _casting = _casting or Casting()
    _casting.design(description, text, out)
    others = {o: preprod.PROJECT / chosen_voice(v)["path"] for o, v in voices.items() if o != cid and chosen_voice(v)}
    likeness = _casting.likeness(out, others)
    seconds = round(duration(out), 2)
    problems = []
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        problems.append(f"the reference is {seconds} s; write a text that takes {MIN_SECONDS:g}-{MAX_SECONDS:g} s to say (about 15-30 words)")
    close = {o: s for o, s in likeness.items() if s > MAX_LIKENESS}
    if close:
        problems.append("sounds too like " + ", ".join(f"{o} ({s})" for o, s in close.items())
                        + ": change at least two of gender, age, pitch, pace and timbre")  # fmt: skip
    entry["candidates"].append({"n": n, "description": description, "text": text,
                                "path": str(out.relative_to(preprod.PROJECT)), "seconds": seconds, "likeness": likeness})  # fmt: skip
    if not problems:
        entry["chosen"] = n
    preprod.save(pid, "voices", voices)
    if not problems:
        _into_plan(pid, cid, entry)
    _update_step(pid, voices)
    return {"ok": not problems, "voice": str(out.relative_to(preprod.PROJECT)), "seconds": seconds,
            "likeness": likeness, "problems": problems}  # fmt: skip


def choose_voice(pid: str, cid: str, n: int) -> None:
    from . import preprod

    voices = preprod.load(pid, "voices") or {}
    entry = voices.get(cid)
    if not entry or not any(c["n"] == n for c in entry["candidates"]):
        raise ValueError(f"no voice candidate {n} for {cid}")
    entry["chosen"] = n
    preprod.save(pid, "voices", voices)
    _into_plan(pid, cid, entry)
    _update_step(pid, voices)


def chosen_voice(entry: dict | None) -> dict | None:
    if not entry or not entry.get("chosen"):
        return None
    return next(c for c in entry["candidates"] if c["n"] == entry["chosen"])


def _into_plan(pid: str, cid: str, entry: dict) -> None:
    """A voice chosen after the shot plan was saved goes straight into the plan the renderer reads."""
    import json
    import os

    from . import preprod

    plan_file = preprod.folder(pid) / "plan.json"
    if not plan_file.exists():
        return
    plan = json.loads(plan_file.read_text())
    if cid in plan["characters"]:
        voice = chosen_voice(entry)
        plan["characters"][cid].update(voice=os.path.relpath(preprod.PROJECT / voice["path"], plan_file.parent), voice_text=voice["text"])
        plan_file.write_text(json.dumps(plan, indent=2))


def _update_step(pid: str, voices: dict) -> None:
    from . import preprod
    from .api import store

    play = preprod.load(pid, "screenplay") or {"scenes": []}
    speakers = {b["character"] for s in play["scenes"] for b in s["beats"] if b.get("line") and b.get("character")}
    cast_all = speakers and all(chosen_voice(voices.get(s)) for s in speakers)
    store.set_step(pid, "voice", "awaiting_approval" if cast_all else "running")


def main() -> None:
    """python -m storyvid.casting recast <production> <character> — reads preprod/voices/recast_<character>.json."""
    import argparse
    import json
    import time

    from . import preprod
    from .events import EventLog

    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("task", choices=["recast"])
    ap.add_argument("production")
    ap.add_argument("character")
    args = ap.parse_args()
    folder = preprod.folder(args.production) / "voices"
    events = EventLog(folder)
    events.emit("run_started", character=args.character)
    try:
        request = json.loads((folder / f"recast_{args.character}.json").read_text())
        result = cast_voice(args.production, args.character, request["description"], request["text"])
        print(json.dumps(result, indent=2), flush=True)
        events.emit("run_finished", **result)
    except Exception as exc:
        events.emit("run_failed", error=f"{type(exc).__name__}: {exc}")
        from .api import store

        store.set_step(args.production, "voice", "awaiting_approval")
        raise
    finally:
        print(time.strftime("%H:%M:%S"), "done", flush=True)


if __name__ == "__main__":
    main()
