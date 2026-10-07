"""Render a plan into a film: render each shot, check it, re-render what fails, cut it together.

Per take, the checks are:
  words       Whisper transcript of LTX's performance vs the line (on-camera lines)
  speaker     Claude, from the cast sheets and four frames: the line's speaker is the one talking and nobody
              else is (on-camera lines); nobody in view talks over an off-camera line. Dubbed plans only
  dub         the cast voice could be timed to the performance's words (dubbed plans)
  voice       older plans: LTX's voice vs the approved takes, a gate; dubbed plans: the dub vs the cast
              voice, information only, since the voice is the same by construction
  identity    head crops vs the canonical look — ranks takes, no pass mark (light differs by scene)
  continuity  head crops vs the shot it continues, when that shot shows the same character. A gate in
              older plans; information only in dubbed plans, whose speaker check judges who is on screen
              (on photoreal faces the head-crop score can't tell people apart)

In dubbed plans Claude also judges who is in frame (the head detector misses photoreal faces when the
feature it looks for, such as a hairstyle, is cropped), so "character not found" only gates older plans.

A failure that a new seed rarely fixes (speaker not in frame, someone else talking, no character found)
gets one retry before the shot goes to review; other failures get up to EXTRA_TAKES retries.

Run:  uv run python -m storyvid.pipeline stage1/plan.json --out stage1/out/elio
"""

import argparse
import hashlib
import json
import os
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from dotenv import load_dotenv

from . import soundtrack
from .assemble import Clip, assemble, picture
from .dub import OFF_CAMERA_LEAD_S, Dubber, DubError, listen, words
from .dub import SR as VOICE_SR
from .events import EventLog
from .media import Renderer, contact_sheet, duration, extract_audio, ffmpeg, file_sha1, frames, frames_for, last_frame
from .plan import Plan, Shot, build_prompt, load_plan, speaker_problems
from .qa import CharacterScorer, SpeakerCheck, VoiceScorer, centroid, check_speaker, cosine, word_error_rate
from .vision import vision_model

PROJECT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT / "models" / "ltx-2.5-mlx-q8"
RUNTIME_DIR = PROJECT / "ltx-2-mlx"
STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"

MAX_WER = 0.2
MIN_VOICE = 0.78  # Stage 0: Elio 0.85–0.90, every other voice ≤ 0.67
MIN_CONTINUITY = 0.72
EXTRA_TAKES = 2  # re-renders allowed when no take passes
STRUCTURAL = ("speaker not in frame", "someone else talks", "character not found", "character not in frame")
SCENE_FADE = 0.3
OFF_CAMERA_TAIL_S = 0.5
VOICE_LEAD_S, VOICE_TAIL_S = 0.6, 0.7  # line_timing "voice": room around the line for LTX to start and finish
BED_MAX_WORDS = 2  # Whisper hears a word or two in plain room tone; more means LTX put speech in the shot
LEAD_KEEP_S, TAIL_KEEP_S, MIN_SHOT_S = 0.4, 0.6, 2.0  # a line's shot is cut this close around the speech
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
    speaker: str | None = None  # who Claude saw talking (dubbed plans)
    speaker_note: str | None = None
    dub: str | None = None  # the take's picture with the cast voice, for comparing with LTX's own
    dub_words: str | None = None  # words timed to the performance / words in the line
    speech: list[float] | None = None  # on-camera lines: where the cast voice sits in the take (start, end s)
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
        self.dubbed = plan.dubbed
        if self.dubbed:
            problems = speaker_problems(plan)
            if problems:
                raise ValueError("the plan puts the wrong person on screen for a line:\n  " + "\n  ".join(problems))
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("a dubbed plan needs ANTHROPIC_API_KEY for the speaker check")
        self.events.emit("phase", name="loading_checkers")
        self.renderer = Renderer(PROJECT, MODEL_DIR, RUNTIME_DIR, plan.width, plan.height, plan.fps, plan.line_seconds)
        self.stt = load_model(STT_MODEL)
        self.voices = VoiceScorer(with_qwen=False)
        self.faces = CharacterScorer()
        self.dubber = Dubber(self.stt, out / "voice") if self.dubbed else None
        self.by_id = {s.id: s for s in plan.shots()}
        if self.dubbed:  # the dub vs the cast voice
            self.voice_ref = {cid: self.voices.embed(c.voice)["resemblyzer"] for cid, c in plan.characters.items() if c.voice}
        else:  # LTX's voice vs the approved takes; characters without approved takes (no audition) skip the gate
            self.voice_ref = {
                cid: centroid([self.voices.embed(p)["resemblyzer"] for p in c.voice_refs])
                for cid, c in plan.characters.items()
                if c.voice_refs
            }
        self.look_ref = {
            cid: self._head_embedding([open_rgb(c.canonical_image)], c.head_query)
            for cid, c in plan.characters.items()
        }
        self.anchor_refs: dict[tuple[str, str], np.ndarray | None] = {}
        self.results: dict[str, ShotResult] = {}
        self.head_embs: dict[str, list[np.ndarray]] = {}  # chosen take per shot → per-frame head embeddings
        self.beds: dict[str, str] = {}  # scene → the shot whose sound is its ambience

    def _anchor_ref(self, image: Path, query: str):
        key = (str(image), query)
        if key not in self.anchor_refs:
            self.anchor_refs[key] = self._head_embedding([open_rgb(image)], query)
        return self.anchor_refs[key]

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

    # ------------------------------------------------------------ shooting

    def shoot(self, shot: Shot) -> ShotResult:
        prompt = build_prompt(self.plan, shot)
        image = self._start_image(shot)
        cast_line = self._cast_line(shot)
        frames_n = self._frames(shot, cast_line)
        takes: list[Take] = []
        embs_by_take: dict[int, list[np.ndarray]] = {}
        structural = 0
        for k in range(shot.takes + EXTRA_TAKES):
            seed = seed_for(shot.id, k)
            key = self.renderer.cache_key(prompt, seed, frames_n, image)
            path = self.out / "takes" / f"{shot.id}_t{k}_{key}.mp4"
            cached = path.exists()
            log(f"[{shot.id}] take {k + 1} (seed {seed}) {'cached' if cached else 'rendering…'}")
            self.events.emit("take_started", shot=shot.id, take=k, seed=seed, cached=cached)
            r = self.renderer.render(prompt, path, seed, frames_n, image)
            take = Take(k, seed, str(path), round(r.seconds, 1), r.cached, round(duration(path), 2))
            try:
                take, embs = self.check(shot, take, cast_line)
            except Exception as exc:  # a bug in a check: flag this shot and keep the film going
                log(f"[{shot.id}] check failed:\n{traceback.format_exc()}")
                take.failures.append(f"check error: {type(exc).__name__}: {exc}")
                embs = []
            takes.append(take)
            embs_by_take[k] = embs
            contact_sheet(path, self.out / "contact" / f"{path.stem}.png")
            log(f"[{shot.id}] take {k + 1}: {fmt_take(take)}")
            self.events.emit("take_done", shot=shot.id, **asdict(take), passed=take.passed)
            if len(takes) >= shot.takes and any(t.passed for t in takes):
                break
            if any(f.startswith("check error") for f in take.failures):
                break  # another seed won't fix it
            structural += any(f.startswith(STRUCTURAL) for f in take.failures)
            if structural >= 2:
                log(f"[{shot.id}] the same kind of failure twice: the shot itself needs changing, so it goes to review")
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

    def _cast_line(self, shot: Shot) -> Path | None:
        """Dubbed plans: the line in the speaker's cast voice, made before the picture (it sets off-camera lengths)."""
        if not (self.dubber and shot.line):
            return None
        c = self.plan.characters[shot.speaker]
        return self.dubber.cast_line(c.voice, c.voice_text, shot.line)

    def _frames(self, shot: Shot, cast_line: Path | None) -> int | None:
        if shot.line and shot.delivery == "on":
            if self.plan.line_timing == "voice" and cast_line:
                lo, hi = self.plan.line_seconds
                return frames_for(min(max(VOICE_LEAD_S + duration(cast_line) + VOICE_TAIL_S, lo), hi), self.plan.fps)
            return None  # LTX's DurationHead fits the clip to the line, within plan.line_seconds
        seconds = shot.seconds
        if cast_line:  # off camera: the picture runs as long as the voice needs
            seconds = max(seconds, OFF_CAMERA_LEAD_S + duration(cast_line) + OFF_CAMERA_TAIL_S)
        return frames_for(seconds, self.plan.fps)

    # ------------------------------------------------------------ checks

    def check(self, shot: Shot, take: Take, cast_line: Path | None) -> tuple[Take, list[np.ndarray]]:
        path = Path(take.path)
        if shot.line and shot.delivery == "on":
            wav = extract_audio(path, path.with_suffix(".wav"))
            if self.dubber:
                take.heard, said = listen(self.stt, wav)
            else:
                take.heard, said = self.stt.generate(str(wav), language="en").text.strip(), []
            take.wer = round(word_error_rate(shot.line, take.heard), 3)
            if take.wer > MAX_WER:
                take.failures.append(f"words (WER {take.wer})")
            if self.dubber:
                span = (said[0][1], said[-1][2]) if said else (0.5, take.seconds - 0.5)
                self._check_speaker(shot, take, span, on_camera=True)
                self._dub(shot, take, cast_line, said)
            elif shot.character in self.voice_ref:
                take.voice = round(cosine(self.voice_ref[shot.character], self.voices.embed(wav)["resemblyzer"]), 3)
                if take.voice < MIN_VOICE:
                    take.failures.append(f"voice ({take.voice})")
        elif self.dubber:
            # Silent and off-camera shots keep their own sound in a dubbed film, unless LTX put speech in it.
            take.heard = self.stt.generate(str(extract_audio(path, path.with_suffix(".wav"))), language="en").text.strip()
            if shot.line:  # off camera: the cast voice over the picture, and nobody in view may talk
                self._save_voice(shot, take, self.dubber.lay_over(cast_line, take.seconds).track)
                if shot.character:
                    span = (OFF_CAMERA_LEAD_S, min(take.seconds - 0.2, OFF_CAMERA_LEAD_S + duration(cast_line)))
                    self._check_speaker(shot, take, span, on_camera=False)
        embs: list[np.ndarray] = []
        if shot.character and shot.identity_check:
            query = self.plan.characters[shot.character].head_query
            sampled = frames(path)
            embs = [e for e in (self.faces.embed_character(f, query) for f in sampled) if e is not None]
            take.heads = f"{len(embs)}/{len(sampled)}"
            if not embs:
                if not self.dubbed:
                    take.failures.append("character not found")
            else:
                # An anchored shot is measured against its own keyframe: same scene, same light. Comparing a
                # night interior with a golden-hour reference mostly measures the lighting.
                ref = self._anchor_ref(shot.image, query) if shot.start == "anchor" and shot.image else None
                ref = ref if ref is not None else self.look_ref[shot.character]
                take.identity = round(float(np.mean([cosine(ref, e) for e in embs])), 3)
                prev = self.by_id[shot.from_shot] if shot.start == "continue" else None
                if prev and prev.character == shot.character and self.head_embs.get(prev.id):
                    take.continuity = round(float(np.mean([cosine(centroid(self.head_embs[prev.id]), e) for e in embs])), 3)
                    if take.continuity < MIN_CONTINUITY and not self.dubbed:
                        take.failures.append(f"continuity ({take.continuity})")
        return take, embs

    def _cast_sheets(self, scene_id: str) -> dict[str, Path]:
        """Everyone who appears or speaks in the scene, by name, with the image the speaker check knows them by."""
        ids = dict.fromkeys(c for s in self.plan.scene(scene_id).shots for c in (s.character, s.speaker) if c)
        return {self.plan.characters[c].name: self.plan.characters[c].sheet or self.plan.characters[c].canonical_image for c in ids}

    def _check_speaker(self, shot: Shot, take: Take, span: tuple[float, float], on_camera: bool) -> None:
        path = Path(take.path)
        cast = self._cast_sheets(shot.scene_id)
        speaker = self.plan.characters[shot.speaker].name if on_camera else None
        in_frame = self.plan.characters[shot.character].name if shot.character and not on_camera else None
        key = hashlib.sha1(json.dumps([path.name, speaker, in_frame, shot.line, [round(span[0], 2), round(span[1], 2)],
                                       {n: file_sha1(p) for n, p in cast.items()}, vision_model()]).encode()).hexdigest()  # fmt: skip
        cache = path.with_suffix(".speaker.json")
        saved = json.loads(cache.read_text()) if cache.exists() else {}
        if saved.get("key") == key:
            verdict = SpeakerCheck(**saved["verdict"])
        else:
            try:
                verdict = check_speaker(path, span, cast, shot.line, speaker, in_frame)
            except Exception as exc:  # the check needs the network; a long render shouldn't die with it
                take.speaker, take.speaker_note = "unchecked", f"{type(exc).__name__}: {exc}"
                log(f"[{shot.id}] speaker check failed: {take.speaker_note}")
                return
            cache.write_text(json.dumps({"key": key, "verdict": verdict.model_dump()}, indent=2))
        take.speaker, take.speaker_note = verdict.who_is_talking, verdict.note
        if on_camera:
            if not verdict.speaker_visible:
                take.failures.append("speaker not in frame")
            elif not verdict.speaker_is_talking:
                take.failures.append("speaker not talking")
            if verdict.someone_else_talking:
                take.failures.append("someone else talks")
        else:
            if in_frame and not verdict.speaker_visible:
                take.failures.append("character not in frame")
            if verdict.speaker_is_talking or verdict.someone_else_talking:
                take.failures.append("someone in view talks")

    def _dub(self, shot: Shot, take: Take, cast_line: Path, said: list[tuple[str, float, float]]) -> None:
        try:
            dub = self.dubber.dub(said, cast_line, shot.line, take.seconds)
            take.dub_words = f"{dub.words_found}/{len(words(shot.line))}"
        except DubError as exc:
            take.failures.append(f"dub ({exc})")
            dub = self.dubber.lay_over(cast_line, take.seconds)  # if this take is still the best, the line is heard
        self._save_voice(shot, take, dub.track)
        # Whisper's first word often starts with the silence before it; the placed voice is exact.
        voiced = np.nonzero(np.abs(dub.track) > 1e-3)[0]
        take.speech = [round(voiced[0] / VOICE_SR, 2), round(voiced[-1] / VOICE_SR, 2)] if len(voiced) else None

    def _save_voice(self, shot: Shot, take: Take, track: np.ndarray) -> None:
        path = Path(take.path)
        wav = path.with_suffix(".dub.wav")
        sf.write(wav, track, VOICE_SR)
        preview = path.with_suffix(".dub.mp4")
        ffmpeg("-i", str(path), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
               "-c:a", "aac", "-b:a", "128k", "-shortest", str(preview))  # fmt: skip
        take.dub = str(preview)
        if shot.speaker in self.voice_ref:
            take.voice = round(cosine(self.voice_ref[shot.speaker], self.voices.embed(wav)["resemblyzer"]), 3)

    # ------------------------------------------------------------ the cut

    def cut(self) -> None:
        shots = self.plan.shots()
        clips = []
        for i, shot in enumerate(shots):
            res = self.results[shot.id]
            first_in_scene = i == 0 or shots[i - 1].scene_id != shot.scene_id
            last_in_scene = i == len(shots) - 1 or shots[i + 1].scene_id != shot.scene_id
            start, end = self._cut_points(shots, i)
            clips.append(Clip(
                path=Path(res.takes[res.chosen].path),
                trim_start=start,
                fade_in=(0.5 if i == 0 else SCENE_FADE) if first_in_scene else 0.0,
                fade_out=(1.0 if i == len(shots) - 1 else SCENE_FADE) if last_in_scene else 0.0,
                end=end,
            ))  # fmt: skip
        work = self.out / "assembly"
        parts = picture(clips, work, self.plan.fps, self.plan.width, self.plan.height)
        self.beds = self._bed_sources() if self.dubbed else {}
        placed, at = [], 0.0
        for shot, clip, part in zip(shots, clips, parts):
            length = duration(part)
            voice = None
            if self.dubbed and shot.line:
                dub = clip.path.with_suffix(".dub.wav")
                if dub.exists():
                    voice, _ = sf.read(dub, dtype="float32")
                else:  # its checks failed before the dub: lay the cast voice over the picture
                    voice = self.dubber.lay_over(self._cast_line(shot), duration(clip.path)).track
            placed.append(soundtrack.Placed(
                shot.scene_id, clip.path, at, length, clip.trim_start, clip.fade_in, clip.fade_out, voice,
                native=not self.dubbed or self._clean(shot), bed_source=self.beds.get(shot.scene_id) == shot.id,
            ))  # fmt: skip
            at += length
        track = soundtrack.build(placed, self.dubbed, work / "soundtrack.wav")
        film = assemble(parts, track, self.out / "final.mp4", work, DISCLOSURE)
        log(f"film: {film} ({duration(film):.1f} s)")

    def _cut_points(self, shots: list[Shot], i: int) -> tuple[float, float | None]:
        """Where shot i starts and ends in its take. A line's shot is cut close around the speech (LTX often acts
        for a second or two before speaking), except where the cut must stay seamless: the head of a shot that
        continues the one just before it, and the tail of a shot that the next one continues."""
        shot = shots[i]
        take = self.results[shot.id].takes[self.results[shot.id].chosen]
        follows = shot.start == "continue" and i > 0 and shot.from_shot == shots[i - 1].id
        start = 1 / self.plan.fps if shot.start == "continue" else 0.0  # its first frame repeats the shot it continues
        end = None
        if self.dubbed and take.speech:
            continued = i + 1 < len(shots) and shots[i + 1].start == "continue" and shots[i + 1].from_shot == shot.id
            if not follows:
                start = max(start, take.speech[0] - LEAD_KEEP_S)
            if not continued:
                end = min(take.seconds, take.speech[1] + TAIL_KEEP_S)
            if (end or take.seconds) - start < MIN_SHOT_S:  # too tight: keep the whole take
                start, end = (1 / self.plan.fps if shot.start == "continue" else 0.0), None
        return start, end

    def _clean(self, shot: Shot) -> bool:
        """Dubbed films: is the chosen take's own sound usable, i.e. no on-camera line and no speech LTX made up?"""
        if shot.line and shot.delivery == "on":
            return False
        take = self.results[shot.id].takes[self.results[shot.id].chosen]
        return len(words(take.heard or "")) <= BED_MAX_WORDS

    def _bed_sources(self) -> dict[str, str]:
        """Per scene, the shot whose sound becomes the ambience under its lines: establishing shots first."""
        beds = {}
        for scene in self.plan.scenes:
            for s in sorted(scene.shots, key=lambda s: (s.character is not None, s.line is not None)):
                if self._clean(s):
                    beds[scene.id] = s.id
                    break
            else:
                if any(s.line and s.delivery == "on" for s in scene.shots):
                    log(f"scene {scene.id}: no shot without speech, so its lines have no ambience under them")
        return beds

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
            "| Shot | Start | Takes | Chosen | Length | Words (WER) | Speaker | Dub | Voice | Identity | Continuity | Status |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]  # fmt: skip
        for r in self.results.values():
            t = r.takes[r.chosen]
            status = "needs review: " + ", ".join(t.failures) if r.needs_review else "pass"
            lines.append(
                f"| {r.shot} | {r.start} | {len(r.takes)} | {t.index + 1} (seed {t.seed}) | {t.seconds} s "
                f"| {na(t.wer)} | {na(t.speaker)} | {na(t.dub_words)} | {na(t.voice)} | {na(t.identity)} "
                f"| {na(t.continuity)} | {status} |"
            )
        if self.dubbed:
            lines += ["", "Voices are each character's cast voice, timed to LTX's performance (on camera) or laid over the picture (off camera)."]
            lines += [f"Ambience under the lines of scene {s.id}: " + (f"the sound of {self.beds[s.id]}" if s.id in self.beds else "none (no shot without speech)")
                      for s in self.plan.scenes]  # fmt: skip
        lines += ["", "Contact sheets for every take are in `contact/`; all scores in `plan.resolved.json`."]
        (self.out / "report.md").write_text("\n".join(lines) + "\n")
        log(f"report: {self.out / 'report.md'}")


def open_rgb(path: Path):
    from PIL import Image

    return Image.open(path).convert("RGB")


def severity(take: Take) -> int:
    """How bad a failing take is to use anyway: the wrong person on screen is worse than a missed word."""
    return sum(3 if f.startswith(STRUCTURAL) else 1 for f in take.failures)


def pick(takes: list[Take]) -> Take:
    """Best passing take by identity; if none pass, the take with the fewest and mildest failures."""
    passing = [t for t in takes if t.passed]
    if passing:
        return max(passing, key=lambda t: t.identity if t.identity is not None else 0.0)
    return min(takes, key=lambda t: (severity(t), t.wer or 0.0, -(t.voice or 0.0), -(t.identity or 0.0)))


def na(x) -> str:
    return "—" if x is None else f"{x}"


def fmt_take(t: Take) -> str:
    parts = [f"{t.seconds} s", "cached" if t.cached else f"render {t.render_s} s"]
    for name in ("wer", "speaker", "dub_words", "voice", "identity", "continuity"):
        if getattr(t, name) is not None:
            parts.append(f"{name} {getattr(t, name)}")
    parts.append("PASS" if t.passed else "FAIL: " + ", ".join(t.failures))
    return ", ".join(parts)


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def main() -> None:
    load_dotenv(PROJECT / ".env")  # the speaker check calls Claude; the studio passes its environment already
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
