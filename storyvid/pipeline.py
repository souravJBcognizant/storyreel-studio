"""Render a plan into a film: render each shot, check it, re-render what fails, cut it together.

Per take, the checks are:
  words       Whisper transcript vs the line (shots with a line)
  voice       resemblyzer vs the character's approved voice takes (shots with a line)
  identity    head crops vs the canonical look — ranks takes, no pass mark (light differs by scene)
  continuity  head crops vs the shot it continues — same scene and light, so this one gates

Run:  uv run python -m storyvid.pipeline stage1/plan.json --out stage1/out/elio
"""

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .assemble import Clip, assemble
from .events import EventLog
from .media import Renderer, contact_sheet, duration, extract_audio, frames, frames_for, last_frame
from .plan import Plan, Shot, build_prompt, load_plan
from .qa import CharacterScorer, VoiceScorer, centroid, cosine, word_error_rate

PROJECT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT / "models" / "ltx-2.5-mlx-q8"
RUNTIME_DIR = PROJECT / "ltx-2-mlx"
STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"

MAX_WER = 0.2
MIN_VOICE = 0.78  # Stage 0: Elio 0.85–0.90, every other voice ≤ 0.67
MIN_CONTINUITY = 0.72
EXTRA_TAKES = 2  # re-renders allowed when no take passes
SCENE_FADE = 0.3
DISCLOSURE = "AI-generated with LTX-2.5 (ltx-2-mlx) for non-commercial evaluation."


@dataclass
class Take:
    index: int
    seed: int
    path: str
    render_s: float
    cached: bool
    seconds: float
    heard: str | None = None
    wer: float | None = None
    voice: float | None = None
    identity: float | None = None
    continuity: float | None = None
    heads: str | None = None  # frames with a detected head / frames sampled
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass
class ShotResult:
    shot: str
    scene: str
    start: str
    prompt: str
    start_image: str | None
    takes: list[Take]
    chosen: int
    needs_review: bool


def seed_for(shot_id: str, take: int) -> int:
    return int(hashlib.sha1(shot_id.encode()).hexdigest(), 16) % 100_000 + 7919 * take


class Director:
    def __init__(self, plan: Plan, out: Path):
        from mlx_audio.stt.utils import load_model

        self.plan, self.out = plan, out
        for sub in ("takes", "anchors", "contact"):
            (out / sub).mkdir(parents=True, exist_ok=True)
        self.events = EventLog(out)
        self.events.emit("run_started", title=plan.title,
                         shots=[{"id": s.id, "scene": s.scene_id, "takes": s.takes} for s in plan.shots()])  # fmt: skip
        self.events.emit("phase", name="loading_checkers")
        self.renderer = Renderer(PROJECT, MODEL_DIR, RUNTIME_DIR, plan.width, plan.height, plan.fps)
        self.stt = load_model(STT_MODEL)
        self.voices = VoiceScorer(with_qwen=False)
        self.faces = CharacterScorer()
        self.voice_ref = {
            cid: centroid([self.voices.embed(p)["resemblyzer"] for p in c.voice_refs])
            for cid, c in plan.characters.items()
        }
        self.look_ref = {
            cid: self._head_embedding([open_rgb(c.canonical_image)], c.head_query)
            for cid, c in plan.characters.items()
        }
        self.results: dict[str, ShotResult] = {}
        self.head_embs: dict[str, list[np.ndarray]] = {}  # chosen take per shot → per-frame head embeddings

    def _head_embedding(self, images, query):
        embs = [e for e in (self.faces.embed_character(im, query) for im in images) if e is not None]
        return centroid(embs) if embs else None

    def run(self) -> None:
        t0 = time.perf_counter()
        self.events.emit("phase", name="rendering")
        for shot in self.plan.shots():
            self.results[shot.id] = res = self.shoot(shot)
            self._save()
            self.events.emit("shot_done", shot=shot.id, chosen=res.chosen, takes=len(res.takes),
                             needs_review=res.needs_review)  # fmt: skip
        self.events.emit("phase", name="assembling")
        self.cut()
        self.report(time.perf_counter() - t0)
        (self.out / "plan.resolved.partial.json").replace(self.out / "plan.resolved.json")
        film = self.out / "final.mp4"
        self.events.emit("film_done", path=str(film), seconds=round(duration(film), 2),
                         wall_s=round(time.perf_counter() - t0, 1))  # fmt: skip

    def shoot(self, shot: Shot) -> ShotResult:
        prompt = build_prompt(self.plan, shot)
        image = self._start_image(shot)
        frames_n = None if shot.line else frames_for(shot.seconds, self.plan.fps)
        takes: list[Take] = []
        embs_by_take: dict[int, list[np.ndarray]] = {}
        for k in range(shot.takes + EXTRA_TAKES):
            seed = seed_for(shot.id, k)
            key = self.renderer.cache_key(prompt, seed, frames_n, image)
            path = self.out / "takes" / f"{shot.id}_t{k}_{key}.mp4"
            cached = path.exists()
            log(f"[{shot.id}] take {k + 1} (seed {seed}) {'cached' if cached else 'rendering…'}")
            self.events.emit("take_started", shot=shot.id, take=k, seed=seed, cached=cached)
            r = self.renderer.render(prompt, path, seed, frames_n, image)
            take, embs = self.check(shot, Take(k, seed, str(path), round(r.seconds, 1), r.cached, round(duration(path), 2)))
            takes.append(take)
            embs_by_take[k] = embs
            contact_sheet(path, self.out / "contact" / f"{path.stem}.png")
            log(f"[{shot.id}] take {k + 1}: {fmt_take(take)}")
            self.events.emit("take_done", shot=shot.id, **asdict(take), passed=take.passed)
            if len(takes) >= shot.takes and any(t.passed for t in takes):
                break
        chosen = pick(takes)
        self.head_embs[shot.id] = embs_by_take[chosen.index]
        return ShotResult(shot.id, shot.scene_id, shot.start, prompt, str(image) if image else None,
                          takes, chosen.index, not chosen.passed)  # fmt: skip

    def _start_image(self, shot: Shot) -> Path | None:
        if shot.start == "anchor":
            return shot.image
        if shot.start == "continue":
            prev = self.results[shot.from_shot]
            src = Path(prev.takes[prev.chosen].path)
            return last_frame(src, self.out / "anchors" / f"{shot.id}_from_{src.stem}.png")
        return None

    def check(self, shot: Shot, take: Take) -> tuple[Take, list[np.ndarray]]:
        path = Path(take.path)
        if shot.line:
            wav = extract_audio(path, path.with_suffix(".wav"))
            take.heard = self.stt.generate(str(wav), language="en").text.strip()
            take.wer = round(word_error_rate(shot.line, take.heard), 3)
            take.voice = round(cosine(self.voice_ref[shot.character], self.voices.embed(wav)["resemblyzer"]), 3)
            if take.wer > MAX_WER:
                take.failures.append(f"words (WER {take.wer})")
            if take.voice < MIN_VOICE:
                take.failures.append(f"voice ({take.voice})")
        embs: list[np.ndarray] = []
        if shot.character and shot.identity_check:
            query = self.plan.characters[shot.character].head_query
            sampled = frames(path)
            embs = [e for e in (self.faces.embed_character(f, query) for f in sampled) if e is not None]
            take.heads = f"{len(embs)}/{len(sampled)}"
            if not embs:
                take.failures.append("character not found")
            else:
                take.identity = round(float(np.mean([cosine(self.look_ref[shot.character], e) for e in embs])), 3)
                if shot.start == "continue" and self.head_embs.get(shot.from_shot):
                    prev = centroid(self.head_embs[shot.from_shot])
                    take.continuity = round(float(np.mean([cosine(prev, e) for e in embs])), 3)
                    if take.continuity < MIN_CONTINUITY:
                        take.failures.append(f"continuity ({take.continuity})")
        return take, embs

    def cut(self) -> None:
        clips = []
        shots = self.plan.shots()
        for i, shot in enumerate(shots):
            res = self.results[shot.id]
            first_in_scene = i == 0 or shots[i - 1].scene_id != shot.scene_id
            last_in_scene = i == len(shots) - 1 or shots[i + 1].scene_id != shot.scene_id
            clips.append(Clip(
                path=Path(res.takes[res.chosen].path),
                trim_start=1 / self.plan.fps if shot.start == "continue" else 0.0,
                fade_in=(0.5 if i == 0 else SCENE_FADE) if first_in_scene else 0.0,
                fade_out=(1.0 if i == len(shots) - 1 else SCENE_FADE) if last_in_scene else 0.0,
            ))  # fmt: skip
        film = assemble(clips, self.out / "final.mp4", self.out / "assembly",
                        self.plan.fps, self.plan.width, self.plan.height, DISCLOSURE)  # fmt: skip
        log(f"film: {film} ({duration(film):.1f} s)")

    def _save(self) -> None:
        data = {sid: {**asdict(r), "takes": [{**asdict(t), "passed": t.passed} for t in r.takes]}
                for sid, r in self.results.items()}  # fmt: skip
        # Partial results stay in their own file until the film is cut (see run), so a cancelled or
        # failed re-render never overwrites the last complete results.
        (self.out / "plan.resolved.partial.json").write_text(json.dumps(data, indent=2))

    def report(self, wall_s: float) -> None:
        renders = [t for r in self.results.values() for t in r.takes if not t.cached]
        lines = [
            f"# {self.plan.title} — render report", "",
            f"Film: `final.mp4` ({duration(self.out / 'final.mp4'):.1f} s). "
            f"Wall time {wall_s / 60:.1f} min, {len(renders)} new renders "
            f"({sum(t.render_s for t in renders) / 60:.1f} min of LTX).", "",
            "| Shot | Start | Takes | Chosen | Length | Words (WER) | Voice | Identity | Continuity | Status |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]  # fmt: skip
        for r in self.results.values():
            t = r.takes[r.chosen]
            status = "needs review: " + ", ".join(t.failures) if r.needs_review else "pass"
            lines.append(
                f"| {r.shot} | {r.start} | {len(r.takes)} | {t.index + 1} (seed {t.seed}) | {t.seconds} s "
                f"| {na(t.wer)} | {na(t.voice)} | {na(t.identity)} | {na(t.continuity)} | {status} |"
            )
        lines += ["", "Contact sheets for every take are in `contact/`; all scores in `plan.resolved.json`."]
        (self.out / "report.md").write_text("\n".join(lines) + "\n")
        log(f"report: {self.out / 'report.md'}")


def open_rgb(path: Path):
    from PIL import Image

    return Image.open(path).convert("RGB")


def pick(takes: list[Take]) -> Take:
    """Best passing take by identity; if none pass, the take with the fewest and mildest failures."""
    passing = [t for t in takes if t.passed]
    if passing:
        return max(passing, key=lambda t: t.identity if t.identity is not None else 0.0)
    return min(takes, key=lambda t: (len(t.failures), t.wer or 0.0, -(t.voice or 0.0), -(t.identity or 0.0)))


def na(x) -> str:
    return "—" if x is None else f"{x}"


def fmt_take(t: Take) -> str:
    parts = [f"{t.seconds} s", "cached" if t.cached else f"render {t.render_s} s"]
    for name in ("wer", "voice", "identity", "continuity"):
        if getattr(t, name) is not None:
            parts.append(f"{name} {getattr(t, name)}")
    parts.append("PASS" if t.passed else "FAIL: " + ", ".join(t.failures))
    return ", ".join(parts)


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        Director(load_plan(args.plan), out).run()
    except Exception as exc:
        EventLog(out).emit("run_failed", error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
