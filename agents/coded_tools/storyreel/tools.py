"""Coded tools for the storyreel pre-production network.

Every tool reads the production id from sly_data (agents never type it), validates what the agent
hands it, returns compact JSON — including exact errors the agent can fix — and writes its result
to productions/<id>/preprod/ so the step is durable and visible in the app.
"""

import asyncio
import json
import os
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from neuro_san.interfaces.coded_tool import CodedTool
from pydantic import ValidationError

from storyvid import preprod
from storyvid.api import store
from storyvid.plan import load_plan, speaker_problems

BRANDS = re.compile(r"\b(pixar|disney|illumination|dreamworks|ghibli|sony pictures|laika)\b", re.I)
SOFT = re.compile(r"\b(whisper\w*|softly|murmur\w*|under (his|her|their) breath)\b", re.I)
SECONDS_PER_BEAT = 4.0
MAX_LINE_WORDS = 10  # a line fits a 3–6 s shot
MAX_PROPS = 3
IMAGE_WORKERS = 4  # OpenAI image edits in flight at once
LINE_SECONDS = [3, 6]  # a line's shot runs this long at most and at least
LINE_TIMING = "voice"  # sized to the cast voice: 26% less render time than LTX's own choice, same checks passed
START_MODES = ("establishing", "single", "continue", "fresh")


class StoryTool(CodedTool):
    """Shared plumbing: production id from sly_data, JSON in and out, errors returned not raised."""

    async def async_invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> str:
        return await asyncio.to_thread(self.invoke, args, sly_data)

    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> str:
        try:
            return json.dumps(self.run(sly_data["production_id"], args or {}), ensure_ascii=False)
        except ValidationError as exc:
            errors = [{"where": ".".join(map(str, e["loc"])), "problem": e["msg"]} for e in exc.errors()]
            return json.dumps({"ok": False, "errors": errors})
        except Exception as exc:  # the agent decides what to do next
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def run(self, pid: str, args: dict[str, Any]) -> dict:
        raise NotImplementedError


def _rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(preprod.PROJECT))


def _prop_phrase(description: str) -> str:
    """'A sleek black palette with a mirrored lid.' → 'sleek black palette with a mirrored lid', so an action can
    say 'the {palette}'."""
    text = description.strip().rstrip(".")
    return re.sub(r"^(a|an|the)\s+", "", text, flags=re.I)


def _speakers(play: dict) -> list[str]:
    """Characters with at least one line, in order of their first line."""
    return list(dict.fromkeys(b["character"] for s in play["scenes"] for b in s["beats"] if b.get("line") and b.get("character")))


# ------------------------------------------------------------------ reading


class ReadProduction(StoryTool):
    def run(self, pid, args):
        prod = preprod.production(pid)
        return {
            "title": prod["title"],
            "story": prod["story"],
            "target_seconds": prod["target_seconds"],
            "already_made": {name: preprod.load(pid, name) is not None for name in ("cast", "screenplay", "voices", "keyframes", "plan")},
        }


class DescribeFirstFrame(StoryTool):
    """Claude vision on the uploaded first frame (cached after the first call)."""

    def run(self, pid, args):
        cached = preprod.load(pid, "frame")
        if cached:
            return cached
        store.set_step(pid, "analysis", "running")
        description = preprod.describe_frame(preprod.first_frame(pid))
        preprod.save(pid, "frame", description)
        return description.model_dump()


class ReadCast(StoryTool):
    def run(self, pid, args):
        return preprod.load(pid, "cast") or {"ok": False, "error": "no cast saved yet"}


class ReadScreenplay(StoryTool):
    def run(self, pid, args):
        return preprod.load(pid, "screenplay") or {"ok": False, "error": "no screenplay saved yet"}


class ReadKeyframes(StoryTool):
    def run(self, pid, args):
        return _keyframes(pid)


class ReadVoices(StoryTool):
    def run(self, pid, args):
        return preprod.load(pid, "voices") or {}


# ------------------------------------------------------------------ saving decisions


class SaveCast(StoryTool):
    def run(self, pid, args):
        cast = preprod.Cast.model_validate(args.get("cast"))
        problems = []
        if not cast.characters:
            problems.append("at least one character is needed")
        for text in [cast.style] + [c.bible for c in cast.characters]:
            if BRANDS.search(text):
                problems.append(f"describe the style in plain words, without naming studios: {BRANDS.search(text).group(0)!r}")
        ids = [c.id for c in cast.characters]
        if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-z][a-z0-9_]*", i) for i in ids):
            problems.append("character ids must be unique lowercase slugs")
        if len(cast.props) > MAX_PROPS:
            problems.append(f"{len(cast.props)} props; keep at most {MAX_PROPS}, the objects the story's action depends on "
                            "that appear in several shots (everything else can be described in the shot)")  # fmt: skip
        if problems:
            return {"ok": False, "errors": problems}
        preprod.save(pid, "cast", cast)
        store.set_step(pid, "analysis", "done")
        return {"ok": True, "characters": ids, "props": list(cast.props)}


class SaveScreenplay(StoryTool):
    def run(self, pid, args):
        play = preprod.Screenplay.model_validate(args.get("screenplay"))
        cast = preprod.load(pid, "cast") or {}
        known = {c["id"] for c in cast.get("characters", [])}
        problems, warnings = [], []
        for scene in play.scenes:
            if scene.beats and scene.beats[0].line:
                warnings.append(f"{scene.id}: opens on a line; open each scene on a silent establishing beat (its sound becomes the scene's ambience)")
            for i, beat in enumerate(scene.beats):
                if beat.line and not beat.character:
                    problems.append(f"{scene.id} beat {i + 1}: a line needs a speaking character")
                if beat.character and beat.character not in known:
                    problems.append(f"{scene.id} beat {i + 1}: unknown character {beat.character!r} (cast: {sorted(known)})")
                if beat.line and len(beat.line.split()) > MAX_LINE_WORDS:
                    problems.append(f"{scene.id} beat {i + 1}: line is {len(beat.line.split())} words; keep lines to {MAX_LINE_WORDS} or fewer (split it into two beats)")
                if beat.delivery and SOFT.search(beat.delivery):
                    warnings.append(f"{scene.id} beat {i + 1}: '{beat.delivery}' — soft or whispered delivery is hard to read on the lips; prefer warm, clear delivery")
        if problems:
            return {"ok": False, "errors": problems}
        target = preprod.production(pid)["target_seconds"]
        estimate = SECONDS_PER_BEAT * sum(len(s.beats) for s in play.scenes)
        if not 0.6 * target <= estimate <= 1.4 * target:
            warnings.append(f"about {estimate:.0f} s of film for a {target} s target; adjust the number of beats")
        preprod.save(pid, "screenplay", play)
        store.set_step(pid, "plan", "running")  # the shot plan follows once keyframes exist
        return {"ok": True, "scenes": len(play.scenes), "beats": sum(len(s.beats) for s in play.scenes),
                "speakers": _speakers(play.model_dump()), "estimated_seconds": estimate, "warnings": warnings}  # fmt: skip


# ------------------------------------------------------------------ voices (Qwen3-TTS, local)

_casting_lock = threading.Lock()  # one voice model, one generation at a time


class CastVoice(StoryTool):
    """Designs one character's voice from a description and checks it against the voices already cast."""

    def run(self, pid, args):
        from storyvid.casting import cast_voice

        with _casting_lock:
            result = cast_voice(pid, args["character_id"], args["description"].strip(), args["text"].strip())
        return {**result, "advice": "cast — move on" if result["ok"] else "rewrite and cast again"}


# ------------------------------------------------------------------ images (OpenAI) and their review (Claude)


def _artist():
    from storyvid.keyframes import KeyframeArtist

    return KeyframeArtist()


def _keyframes(pid: str) -> dict:
    state = preprod.load(pid, "keyframes") or {}
    for key in ("sheets", "props", "scenes"):
        state.setdefault(key, {})
    return state


# Agents call tools in parallel (Claude issues several calls in one turn), and image tools run for a minute,
# so keyframes.json is only ever changed under this lock, re-read right before each change.
_state_lock = threading.RLock()


def _update_keyframes(pid: str, change) -> dict:
    with _state_lock:
        state = _keyframes(pid)
        change(state)
        preprod.save(pid, "keyframes", state)
        return state


def _entry(state: dict, sid: str, cid: str | None) -> dict:
    scene = state["scenes"].setdefault(sid, {"candidates": [], "chosen": None, "singles": {}})
    scene.setdefault("singles", {})
    return scene["singles"].setdefault(cid, {"candidates": [], "chosen": None}) if cid else scene


_reserved: dict[tuple[str, str, str | None], int] = {}  # candidate numbers handed to images still being made


def _chosen(entry: dict | None) -> dict | None:
    if not entry or not entry.get("chosen"):
        return None
    return next(c for c in entry["candidates"] if c["n"] == entry["chosen"])


class MakeCharacterSheet(StoryTool):
    def run(self, pid, args):
        return _make_sheets(pid, characters=[args["character_id"]], props=[])


class MakePropSheet(StoryTool):
    def run(self, pid, args):
        return _make_sheets(pid, characters=[], props=[args["prop_id"]])


class MakeReferenceSheets(StoryTool):
    """Every missing character and prop sheet, made in parallel."""

    def run(self, pid, args):
        cast, state = preprod.load(pid, "cast"), _keyframes(pid)
        characters = [c["id"] for c in cast["characters"] if c["id"] not in state["sheets"]]
        props = [p for p in cast["props"] if p not in state["props"]]
        return _make_sheets(pid, characters, props)


def _make_sheets(pid: str, characters: list[str], props: list[str]) -> dict:
    cast = preprod.load(pid, "cast")
    bible = {c["id"]: c["bible"] for c in cast["characters"]}
    first = preprod.first_frame(pid)
    refs = preprod.folder(pid) / "refs"
    store.set_step(pid, "sheets", "running")
    artist = _artist()
    jobs = [("sheets", cid, lambda cid=cid: artist.character_sheet(first, bible[cid], refs / f"{cid}_sheet.png")) for cid in characters]
    jobs += [("props", p, lambda p=p: artist.prop_sheet(p, cast["props"][p], first, refs / f"{p}_prop.png")) for p in props]
    made, errors = {}, {}
    with ThreadPoolExecutor(IMAGE_WORKERS) as pool:
        futures = {(kind, key): pool.submit(make) for kind, key, make in jobs}
    results = {}
    for (kind, key), f in futures.items():
        try:
            results[(kind, key)] = made[key] = _rel(f.result().path)
        except Exception as exc:
            errors[key] = f"{type(exc).__name__}: {exc}"

    def record(state):
        for (kind, key), path in results.items():
            state[kind][key] = path

    _update_keyframes(pid, record)
    return {"ok": not errors, "made": made, "errors": errors}


class MakeKeyframes(StoryTool):
    """Candidate keyframes, made in parallel and each reviewed by Claude against the sheets.

    An entry without character_id is a scene's establishing frame; one with character_id is that
    character's single in the scene, made in the set and light of the scene's chosen establishing frame.
    """

    def run(self, pid, args):
        from storyvid.keyframes import fit_frame

        cast, state = preprod.load(pid, "cast"), _keyframes(pid)
        play = preprod.load(pid, "screenplay")
        scenes = {s["id"]: s for s in play["scenes"]}
        chars = {c["id"]: c for c in cast["characters"]}
        first = preprod.first_frame(pid)
        if not state["sheets"]:
            return {"ok": False, "error": "make the reference sheets first (MakeReferenceSheets)"}
        store.set_step(pid, "sheets", "done")
        store.set_step(pid, "keyframes", "running")
        prop_sheets = {p: preprod.PROJECT / path for p, path in state["props"].items()}
        work, errors = [], []
        with _state_lock:  # number the new candidates; images still being made keep their numbers reserved
            state = _keyframes(pid)
            for item in args.get("frames", []):
                sid, cid, description = item.get("scene_id"), item.get("character_id"), (item.get("description") or "").strip()
                if sid not in scenes or not description:
                    errors.append({"frame": item, "error": f"needs a known scene_id ({sorted(scenes)}) and a description"})
                    continue
                scene = _entry(state, sid, None)
                if cid:
                    if cid not in chars or cid not in state["sheets"]:
                        errors.append({"frame": item, "error": f"no sheet for character {cid!r}"})
                        continue
                    if not _chosen(scene):
                        errors.append({"frame": item, "error": f"choose {sid}'s establishing frame first; singles are made in its set and light"})
                        continue
                entry = _entry(state, sid, cid)
                n = max([c["n"] for c in entry["candidates"]] + [_reserved.get((pid, sid, cid), 0)]) + 1
                _reserved[(pid, sid, cid)] = n
                name = f"kf_{sid}_{cid}_v{n}" if cid else f"kf_{sid}_v{n}"
                work.append({"sid": sid, "cid": cid, "n": n, "description": description,
                             "raw": preprod.folder(pid) / "refs" / f"{name}.png",
                             "establishing": preprod.PROJECT / _chosen(scene)["frame"] if cid else None})  # fmt: skip

        def named(text: str, words: str) -> bool:
            return words.lower().replace("_", " ") in text.lower().replace("_", " ")

        def make(w):
            artist = _artist()
            # Only the props and people this frame is about, or the image model tends to add the others.
            props = [p for name, p in prop_sheets.items() if named(w["description"], name)]
            if w["cid"]:
                sheet = preprod.PROJECT / state["sheets"][w["cid"]]
                result = artist.single_keyframe(sheet, w["establishing"], props, w["description"], w["raw"])
                sheets = {chars[w["cid"]]["name"]: sheet}
            else:
                in_scene = {b.get("character") for b in scenes[w["sid"]]["beats"]}
                people = [c for c in chars if c in state["sheets"] and (c in in_scene or named(w["description"], chars[c]["name"].split()[0]))]
                result = artist.scene_keyframe([first, *(preprod.PROJECT / state["sheets"][c] for c in people), *props], w["description"], w["raw"])
                sheets = {chars[c]["name"]: preprod.PROJECT / state["sheets"][c] for c in people}
            frame = fit_frame(w["raw"], w["raw"].with_name(w["raw"].stem + "_frame.png"))
            review = preprod.review_keyframe(sheets, {k: v for k, v in prop_sheets.items() if v in props}, frame,
                                             w["description"], single=chars[w["cid"]]["name"] if w["cid"] else None)  # fmt: skip
            return frame, result.seconds, review

        with ThreadPoolExecutor(IMAGE_WORKERS) as pool:
            futures = [(w, pool.submit(make, w)) for w in work]
        results, made = [], []
        for w, f in futures:
            try:
                frame, seconds, review = f.result()
            except Exception as exc:
                errors.append({"scene_id": w["sid"], "character_id": w["cid"], "error": f"{type(exc).__name__}: {exc}"})
                continue
            candidate = {"n": w["n"], "frame": _rel(frame), "description": w["description"], "review": review.model_dump(), "seconds": seconds}
            made.append((w, candidate))
            good = review.same_character and review.matches_scene and review.single_ok and review.score >= 6
            results.append({"scene_id": w["sid"], "character_id": w["cid"], **candidate,
                            "advice": "good — choose it" if good else "redo with a corrected description"})  # fmt: skip

        def record(state):  # onto the file as it is now: choices made while these images were drawn stay
            for w, candidate in made:
                entry = _entry(state, w["sid"], w["cid"])
                entry["candidates"] = sorted([c for c in entry["candidates"] if c["n"] != w["n"]] + [candidate], key=lambda c: c["n"])

        _update_keyframes(pid, record)
        return {"ok": not errors, "results": results, "errors": errors}


class ChooseKeyframe(StoryTool):
    def run(self, pid, args):
        sid, cid, n = args["scene_id"], args.get("character_id"), int(args["candidate"])
        with _state_lock:
            state = _keyframes(pid)
            scene = state["scenes"].get(sid)
            if scene is None:
                return {"ok": False, "error": f"no keyframes for scene {sid!r}"}
            entry = scene.get("singles", {}).get(cid) if cid else scene
            if not entry or not any(c["n"] == n for c in entry["candidates"]):
                return {"ok": False, "error": f"no candidate {n} for {sid}" + (f" / {cid}" if cid else "")}
            entry["chosen"] = n
            preprod.save(pid, "keyframes", state)
        return {"ok": True, "scene": sid, "character": cid, "chosen": n, "still_needed": _coverage_missing(pid, state)}


def _coverage_missing(pid: str, state: dict) -> list[str]:
    """Keyframes the plan still needs: each scene's establishing frame and a single of everyone who speaks in it."""
    play = preprod.load(pid, "screenplay") or {"scenes": []}
    missing = []
    for s in play["scenes"]:
        scene = state["scenes"].get(s["id"], {})
        if not _chosen(scene):
            missing.append(f"{s['id']}: establishing frame")
        for cid in dict.fromkeys(b["character"] for b in s["beats"] if b.get("line") and b.get("character")):
            if not _chosen(scene.get("singles", {}).get(cid)):
                missing.append(f"{s['id']}: single of {cid}")
    return missing


# ------------------------------------------------------------------ the shot plan


class SavePlan(StoryTool):
    """Turns the planner's shot list into a storyvid plan and validates it exactly as the renderer will."""

    def run(self, pid, args):
        prod = preprod.production(pid)
        cast, play, kf = preprod.load(pid, "cast"), preprod.load(pid, "screenplay"), _keyframes(pid)
        voices = preprod.load(pid, "voices") or {}
        plan_dir = preprod.folder(pid)
        rel = lambda p: os.path.relpath(preprod.PROJECT / p, plan_dir)  # noqa: E731
        scenes_in = {s["id"]: s for s in args.get("scenes", [])}
        errors = [f"no shots for scene {s['id']}" for s in play["scenes"] if s["id"] not in scenes_in]
        scenes = []
        for s in play["scenes"]:
            scene_kf = kf["scenes"].get(s["id"], {})
            establishing = _chosen(scene_kf)
            if not establishing:
                errors.append(f"scene {s['id']} has no chosen establishing frame yet")
                continue
            shots = []
            for i, sh in enumerate(dict(x) for x in scenes_in.get(s["id"], {}).get("shots", [])):
                start = sh.get("start") or ("establishing" if i == 0 else "continue")
                if start not in START_MODES:
                    errors.append(f"{sh.get('id')}: start must be one of {START_MODES}")
                    continue
                if i == 0 and start not in ("establishing", "single"):
                    errors.append(f"{sh.get('id')}: a scene opens on its establishing frame or a speaker's single")
                if start == "fresh" and sh.get("character"):
                    errors.append(f"{sh.get('id')}: a fresh shot has no start frame, so {sh['character']} would be drawn from "
                                  "words alone and look different; start on their single or continue a shot of them")  # fmt: skip
                if start == "establishing":
                    sh.update(start="anchor", image=rel(establishing["frame"]))
                elif start == "single":
                    single = _chosen(scene_kf.get("singles", {}).get(sh.get("character")))
                    if not single:
                        errors.append(f"{sh.get('id')}: no chosen single of {sh.get('character')!r} in {s['id']}; ask for one or use another start")
                        continue
                    sh.update(start="anchor", image=rel(single["frame"]))
                if start != "continue":
                    sh.pop("from", None)
                shots.append(sh)
            scenes.append({"id": s["id"], "setting": s["setting"].rstrip(". "), "audio": s["audio"].rstrip(". "), "shots": shots})
        if errors:
            return {"ok": False, "errors": errors}
        characters = {}
        for c in cast["characters"]:
            sheet = kf["sheets"].get(c["id"])
            voice = _chosen(voices.get(c["id"]))
            characters[c["id"]] = {
                "name": c["name"], "bible": c["bible"].rstrip(". "), "voice_phrase": c["voice_phrase"],
                "head_query": c["head_query"], "voice_refs": [],
                "canonical_image": rel(sheet) if sheet else rel(prod["first_frame"]),
                **({"sheet": rel(sheet)} if sheet else {}),
                **({"voice": rel(voice["path"]), "voice_text": voice["text"]} if voice else {}),
            }  # fmt: skip
        plan = {"title": prod["title"], "fps": 24, "width": 768, "height": 512, "line_seconds": LINE_SECONDS, "line_timing": LINE_TIMING,
                "style": cast["style"].rstrip(". "), "characters": characters,
                "props": {k: _prop_phrase(v) for k, v in cast["props"].items()}, "scenes": scenes}  # fmt: skip
        with tempfile.NamedTemporaryFile("w", suffix=".json", dir=plan_dir, delete=False) as f:
            json.dump(plan, f, indent=2)
        try:
            parsed = load_plan(Path(f.name))
            problems = speaker_problems(parsed) if parsed.dubbed else []
            if not parsed.dubbed and any(s.line for s in parsed.shots()):
                problems.append("every character with a line needs a cast voice (CastingDirector) before the plan can be saved")
        except Exception as exc:
            problems = [str(exc)]
        if problems:
            Path(f.name).unlink()
            return {"ok": False, "errors": problems}
        Path(f.name).replace(plan_dir / "plan.json")
        prod_file = preprod.PRODUCTIONS / pid / "production.json"
        data = json.loads(prod_file.read_text())
        data["plan"] = f"productions/{pid}/preprod/plan.json"
        prod_file.write_text(json.dumps(data, indent=2))
        for step in ("plan", "keyframes"):
            store.set_step(pid, step, "awaiting_approval")
        shots = parsed.shots()
        seconds = sum(sh.seconds or SECONDS_PER_BEAT for sh in shots)
        return {"ok": True, "shots": len(shots), "lines": sum(1 for sh in shots if sh.line), "estimated_seconds": seconds}
