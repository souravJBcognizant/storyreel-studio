"""Productions on disk: one folder per film under productions/, described by production.json.

A production's detail joins four sources: production.json (inputs and stage states), the plan,
the pipeline's plan.resolved.json (finished shots) and events.jsonl (what is happening right now).
"""

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException

from ..events import latest_run
from ..dub import DUB_VERSION
from ..edit import audio_source, load_choices, load_edit, save_choice
from ..media import first_frame, last_frame
from ..plan import load_plan
from .config import (
    IMAGE_ENGINE,
    IMAGE_MODEL,
    LLM_ENGINE,
    LLM_MODEL,
    LLM_MODEL_ROUTINE,
    LOCAL_MODE,
    PRODUCTIONS,
    PROJECT,
    VISION_ENGINE,
    VISION_MODEL,
)
from .files import media_duration, to_virtual

FPS = 24

# The full pipeline, in order. `checkpoint` stages wait for the user's approval.
STAGES = [
    {"key": "story", "label": "Story & reference frames", "owner": "You", "engine": "user",
     "detail": "Upload an opening frame, optional guide and final frames, and write the story"},
    {"key": "analysis", "label": "Story analysis", "owner": "StoryAnalyst", "engine": LLM_ENGINE, "model": LLM_MODEL,
     "detail": "Reads the written story: characters, look, voice and tone" if LOCAL_MODE else
               "Reads the story and the first frame: characters, look, voice, tone"},
    {"key": "plan", "label": "Screenplay & shots", "owner": "Screenwriter · ShotPlanner", "engine": LLM_ENGINE,
     "model": LLM_MODEL, "checkpoint": True, "detail": "Scenes, dialogue and a shot plan you approve"},
    {"key": "sheets", "label": "Character & prop sheets", "owner": "KeyframeArtist", "engine": IMAGE_ENGINE,
     "model": IMAGE_MODEL or "Image model", "detail": "Reference sheets that lock the look"},
    {"key": "keyframes", "label": "Coverage keyframes", "owner": "KeyframeArtist", "engine": IMAGE_ENGINE,
     "model": IMAGE_MODEL or "Image model", "checkpoint": True,
     "detail": "Per scene: an establishing frame and a close-up of everyone who speaks, reviewed against the sheets"},
    {"key": "voice", "label": "Voice casting", "owner": "CastingDirector", "engine": "qwen",
     "model": "Qwen3-TTS VoiceDesign (local)", "checkpoint": True,
     "detail": "Each speaking character's voice, designed once; every line is spoken in it"},
    {"key": "render", "label": "Render & QA", "owner": "ProductionManager", "engine": "ltx",
     "model": "LTX-2.5 (local)",
     "detail": "Every take checked locally for words and voice timing; visual QA is unavailable" if LOCAL_MODE else
               f"Every take checked: the words, who is talking ({VISION_ENGINE}), and the cast voice timed to the performance"},
    {"key": "assemble", "label": "Edit", "owner": "Editor", "engine": "ffmpeg", "model": "ffmpeg",
     "detail": "Cut, fades, scene ambience under the voices, loudness"},
    {"key": "film", "label": "Film", "owner": "You", "engine": "user", "detail": "Watch, download, share"},
]
ROUTINE_MODEL = LLM_MODEL_ROUTINE


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "production"
    candidate, n = slug, 2
    while (PRODUCTIONS / candidate).exists():
        candidate, n = f"{slug}-{n}", n + 1
    return candidate


def _path(rel: str | None) -> Path | None:
    return (PROJECT / rel).resolve() if rel else None


def _read(pid: str) -> dict:
    f = PRODUCTIONS / pid / "production.json"
    if not f.exists():
        raise HTTPException(404, f"no production {pid!r}")
    return json.loads(f.read_text())


def _write(prod: dict) -> None:
    d = PRODUCTIONS / prod["id"]
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "production.json.tmp"
    tmp.write_text(json.dumps(prod, indent=2))
    tmp.replace(d / "production.json")


def set_step(pid: str, step: str, status: str) -> None:
    prod = _read(pid)
    prod["steps"][step] = status
    prod["updated"] = time.time()
    _write(prod)


def register(pid: str, title: str, story: str, first_frame: str, plan: str, out: str, steps: dict,
             source: str, target_seconds: int = 30) -> dict:  # fmt: skip
    """Add a production whose plan already exists (paths are project-relative)."""
    now = time.time()
    prod = {
        "id": pid, "title": title, "created": now, "updated": now, "source": source, "story": story,
        "first_frame": first_frame, "plan": plan, "out": out, "target_seconds": target_seconds,
        "steps": {s["key"]: "pending" for s in STAGES} | steps,
    }  # fmt: skip
    _write(prod)
    return prod


APPROVABLE = ("plan", "keyframes", "voice")


def preprod_dir(pid: str) -> Path:
    d = PRODUCTIONS / pid / "preprod"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ready_to_render(pid: str) -> bool:
    steps = _read(pid)["steps"]
    return all(steps.get(k) in ("done", "skipped") for k in APPROVABLE)


def fail_running_steps(pid: str, value: str) -> None:
    for step, status in _read(pid)["steps"].items():
        if status == "running":
            set_step(pid, step, value)


def approve(pid: str, stage: str) -> None:
    if stage not in APPROVABLE:
        raise HTTPException(400, f"{stage!r} has no approval step")
    if _read(pid)["steps"].get(stage) != "awaiting_approval":
        raise HTTPException(409, f"{stage} is not waiting for approval")
    if stage == "voice" and not (preprod_dir(pid) / "voices.json").exists():
        from ..audition import adopt_voice  # productions from before voice casting approved an LTX audition

        adopt_voice(pid)
    set_step(pid, stage, "done")


def agent_progress(events: list[dict]) -> dict | None:
    """Who is working right now, from the agent trace (see storyvid.agents.trace_event)."""
    if not events:
        return None
    trace = [e for e in events if e["type"] == "trace"]
    finished = next((e for e in reversed(events) if e["type"] in ("run_finished", "run_failed")), None)
    working = None
    for e in trace:  # the deepest agent that has started and not yet answered
        if e["kind"] in ("input", "tool_start"):
            working = e.get("caller") if e["kind"] == "tool_start" else e["agent"]
    tool = next((e for e in reversed(trace) if e["kind"] in ("tool_start", "tool_end")), None)
    said = [e for e in trace if e["kind"] in ("answer", "input")]
    cost = sum(e.get("cost") or 0 for e in trace if e["kind"] == "usage" and "." not in e["path"])
    return {
        "phase": ("finished" if finished["type"] == "run_finished" else "failed") if finished else (working or "starting"),
        "agent": working,
        "tool": tool["agent"] if tool and tool["kind"] == "tool_start" else None,
        "last_text": said[-1]["text"][:500] if said else None,
        "messages": len([e for e in trace if e["kind"] == "answer"]),
        "started": events[0]["t"],
        "last_event": events[-1]["t"],
        "cost": round(cost, 4) if cost else None,
        "error": finished.get("error") if finished and finished["type"] == "run_failed" else None,
    }  # fmt: skip


def ensure_imports() -> None:
    """Register the Stage 1 film as the first production (its files stay where they are)."""
    pid = "elios-first-flight"
    if (PRODUCTIONS / pid / "production.json").exists() or not (PROJECT / "stage1" / "plan.json").exists():
        return
    register(
        pid,
        "Elio's First Flight",
        "Late at night in his cluttered workshop, Elio, a young inventor, finishes a small homemade flying machine. "
        "At golden hour he carries it to the beach, counts down nervously and watches it lift off. From a cliff at "
        "sunset he watches it circle away into the sky.",
        first_frame="stage0/out/ltx/character_ref.png",
        plan="stage1/plan.json",
        out="stage1/out/elio",
        steps={"story": "done", "analysis": "skipped", "plan": "done", "sheets": "skipped", "keyframes": "skipped",
               "voice": "done", "render": "done", "assemble": "done", "film": "done"},  # fmt: skip
        source="Stage 1 test (hand-written plan)",
    )


def create(title: str, story: str, frame_name: str, frame_bytes: bytes, target_seconds: int,
           guide_frames: list[tuple[str, bytes]] | None = None,
           final_frame: tuple[str, bytes] | None = None,
           story_mode: str = "manual", story_prompt: str | None = None,
           story_uses_images: bool | None = None, story_note: str | None = None) -> dict:  # fmt: skip
    pid = slugify(title)
    inputs = PRODUCTIONS / pid / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    ext = Path(frame_name).suffix.lower() or ".png"
    opening_path = inputs / f"first_frame{ext}"
    opening_path.write_bytes(frame_bytes)
    references = [{"role": "opening", "name": frame_name, "path": f"productions/{pid}/inputs/{opening_path.name}"}]
    for i, (name, data) in enumerate(guide_frames or [], 1):
        guide_ext = Path(name).suffix.lower() or ".png"
        path = inputs / f"guide_{i:02d}{guide_ext}"
        path.write_bytes(data)
        references.append({"role": "guide", "name": name, "path": f"productions/{pid}/inputs/{path.name}"})
    if final_frame:
        name, data = final_frame
        final_ext = Path(name).suffix.lower() or ".png"
        path = inputs / f"final_frame{final_ext}"
        path.write_bytes(data)
        references.append({"role": "ending", "name": name, "path": f"productions/{pid}/inputs/{path.name}"})
    (inputs / "story.md").write_text(story)
    now = time.time()
    prod = {
        "id": pid,
        "title": title.strip(),
        "created": now,
        "updated": now,
        "source": "Uploaded",
        "story": story,
        "story_mode": story_mode,
        "story_prompt": story_prompt,
        "story_uses_images": story_uses_images,
        "story_note": story_note,
        "first_frame": f"productions/{pid}/inputs/{opening_path.name}",
        "reference_images": references,
        "plan": None,
        "out": f"productions/{pid}/out",
        "target_seconds": target_seconds,
        "steps": {s["key"]: "pending" for s in STAGES} | {"story": "done"},
    }
    _write(prod)
    return prod


def _remap_clone_value(value, source_dir: Path, target_dir: Path, source_id: str, target_id: str):
    if isinstance(value, dict):
        return {key: _remap_clone_value(item, source_dir, target_dir, source_id, target_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap_clone_value(item, source_dir, target_dir, source_id, target_id) for item in value]
    if isinstance(value, str):
        return value.replace(str(source_dir), str(target_dir)).replace(
            f"productions/{source_id}/", f"productions/{target_id}/"
        )
    return value


def duplicate(pid: str, title: str) -> dict:
    """Create a self-contained copy whose media and metadata can diverge from the source."""
    source = _read(pid)
    if source.get("source", "").startswith("Stage"):
        raise HTTPException(422, "imported test productions cannot be used as templates")
    title = title.strip()
    if len(title) < 2:
        raise HTTPException(422, "give the copied production a title")
    if len(title) > 120:
        raise HTTPException(422, "keep the copied production title under 120 characters")
    target_id = slugify(title)
    source_dir = PRODUCTIONS / pid
    target_dir = PRODUCTIONS / target_id
    try:
        shutil.copytree(source_dir, target_dir, ignore=shutil.ignore_patterns("jobs"))
        for path in target_dir.rglob("*.json"):
            try:
                value = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            remapped = _remap_clone_value(value, source_dir, target_dir, pid, target_id)
            path.write_text(json.dumps(remapped, indent=2))
        for path in target_dir.rglob("*.jsonl"):
            lines = []
            for line in path.read_text().splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    lines.append(line)
                else:
                    lines.append(json.dumps(_remap_clone_value(value, source_dir, target_dir, pid, target_id)))
            path.write_text("\n".join(lines) + ("\n" if lines else ""))
        cloned = json.loads((target_dir / "production.json").read_text())
        now = time.time()
        cloned.update(
            id=target_id,
            title=title,
            created=now,
            updated=now,
            source=f"Copy of {source['title']}",
            source_production=pid,
        )
        plan_path = _path(cloned.get("plan"))
        if plan_path and plan_path.exists():
            plan = json.loads(plan_path.read_text())
            plan["title"] = title
            plan_path.write_text(json.dumps(plan, indent=2))
        _write(cloned)
        return cloned
    except Exception:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        raise


def delete(pid: str) -> None:
    prod = _read(pid)
    if prod.get("source", "").startswith("Stage"):
        raise HTTPException(400, "imported test productions can't be deleted from the app")
    shutil.rmtree(PRODUCTIONS / pid)


def _write_plan(pid: str, raw: dict) -> None:
    """Validate and atomically replace a production plan after a timeline edit."""
    prod = _read(pid)
    plan_path = _path(prod.get("plan"))
    if not plan_path:
        raise HTTPException(409, "this production has no shot plan yet")
    tmp = plan_path.with_suffix(".editing.json")
    tmp.write_text(json.dumps(raw, indent=2))
    try:
        load_plan(tmp)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(422, f"that timeline would make the plan invalid: {exc}") from exc
    tmp.replace(plan_path)
    prod["updated"] = time.time()
    for step in ("render", "assemble", "film"):
        prod["steps"][step] = "pending"
    _write(prod)


def _repair_continuations(raw: dict) -> None:
    """A moved continuation follows the nearest earlier shot if its old source is now later or gone."""
    seen: list[str] = []
    for scene in raw["scenes"]:
        for shot in scene["shots"]:
            if shot.get("start") == "continue":
                source = shot.get("from")
                if not source or source not in seen:
                    if seen:
                        shot["from"] = seen[-1]
                    else:
                        shot["start"] = "fresh"
                        shot.pop("from", None)
            seen.append(shot["id"])


def _raw_plan(pid: str) -> tuple[dict, Path, dict]:
    prod = _read(pid)
    plan_path = _path(prod.get("plan"))
    if not plan_path:
        raise HTTPException(409, "this production has no shot plan yet")
    return prod, plan_path, json.loads(plan_path.read_text())


def _unique_id(base: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")[:40] or "item"
    candidate, n = base, 2
    while candidate in existing:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def _previous_last_shot(raw: dict) -> str | None:
    shots = [shot["id"] for scene in raw["scenes"] for shot in scene["shots"]]
    return shots[-1] if shots else None


def _new_shot(raw: dict, scene_id: str, data: dict) -> dict:
    all_ids = {shot["id"] for scene in raw["scenes"] for shot in scene["shots"]}
    shot_id = _unique_id(data.get("id") or f"{scene_id}_shot", all_ids)
    line = (data.get("line") or "").strip() or None
    character = data.get("character") or None
    speaker = data.get("speaker") or character if line else None
    delivery = data.get("delivery", "on")
    seconds = float(data.get("seconds") or 4)
    if not 0.5 <= seconds <= 60:
        raise HTTPException(422, "shot duration must be between 0.5 and 60 seconds")
    shot = {
        "id": shot_id,
        "start": "fresh",
        "action": (data.get("action") or "A quiet visual beat unfolds.").strip(),
        "camera": (data.get("camera") or "").strip(),
        "seconds": seconds,
        "takes": int(data.get("takes") or 1),
    }
    if character:
        shot["character"] = character
    if line:
        shot.update(line=line, speaker=speaker, delivery=delivery)
    return shot


def reorder_scenes(pid: str, scene_ids: list[str]) -> None:
    _, _, raw = _raw_plan(pid)
    current = [scene["id"] for scene in raw["scenes"]]
    if len(scene_ids) != len(set(scene_ids)) or set(scene_ids) != set(current):
        raise HTTPException(422, "the new order must contain every scene exactly once")
    by_id = {scene["id"]: scene for scene in raw["scenes"]}
    raw["scenes"] = [by_id[sid] for sid in scene_ids]
    _repair_continuations(raw)
    _write_plan(pid, raw)


def update_scene(pid: str, scene_id: str, setting: str, audio: str) -> None:
    _, _, raw = _raw_plan(pid)
    scene = next((scene for scene in raw["scenes"] if scene["id"] == scene_id), None)
    if not scene:
        raise HTTPException(404, f"no scene {scene_id!r}")
    if not setting.strip() or not audio.strip():
        raise HTTPException(422, "a scene needs a setting and sound description")
    scene.update(setting=setting.strip(), audio=audio.strip())
    _write_plan(pid, raw)


def delete_scene(pid: str, scene_id: str) -> None:
    _, _, raw = _raw_plan(pid)
    if not any(scene["id"] == scene_id for scene in raw["scenes"]):
        raise HTTPException(404, f"no scene {scene_id!r}")
    if len(raw["scenes"]) == 1:
        raise HTTPException(422, "a production must keep at least one scene")
    raw["scenes"] = [scene for scene in raw["scenes"] if scene["id"] != scene_id]
    _repair_continuations(raw)
    _write_plan(pid, raw)


def add_shot(pid: str, scene_id: str, data: dict, after: str | None = None) -> str:
    _, _, raw = _raw_plan(pid)
    scene = next((scene for scene in raw["scenes"] if scene["id"] == scene_id), None)
    if not scene:
        raise HTTPException(404, f"no scene {scene_id!r}")
    shot = _new_shot(raw, scene_id, data)
    index = len(scene["shots"])
    if after is not None:
        try:
            index = next(i + 1 for i, item in enumerate(scene["shots"]) if item["id"] == after)
        except StopIteration:
            raise HTTPException(404, f"no shot {after!r} in scene {scene_id!r}") from None
    scene["shots"].insert(index, shot)
    _repair_continuations(raw)
    _write_plan(pid, raw)
    return shot["id"]


def update_shot(pid: str, shot_id: str, data: dict) -> None:
    _, _, raw = _raw_plan(pid)
    shot = next((shot for scene in raw["scenes"] for shot in scene["shots"] if shot["id"] == shot_id), None)
    if not shot:
        raise HTTPException(404, f"no shot {shot_id!r}")
    action = (data.get("action") or "").strip()
    if not action:
        raise HTTPException(422, "a shot needs an action")
    line = (data.get("line") or "").strip() or None
    character = data.get("character") or None
    speaker = data.get("speaker") or character if line else None
    delivery = data.get("delivery", "on")
    seconds = float(data.get("seconds") or 4)
    if not 0.5 <= seconds <= 60:
        raise HTTPException(422, "shot duration must be between 0.5 and 60 seconds")
    shot.update(action=action, camera=(data.get("camera") or "").strip(), seconds=seconds)
    if character:
        shot["character"] = character
    else:
        shot.pop("character", None)
    if line:
        shot.update(line=line, speaker=speaker, delivery=delivery)
    else:
        for field in ("line", "speaker", "delivery"):
            shot.pop(field, None)
    _write_plan(pid, raw)


def _copy_plan_file(value: str, source_root: Path, target_root: Path, target_folder: Path) -> str:
    source = Path(value).expanduser()
    source = source if source.is_absolute() else (source_root / source).resolve()
    if not source.exists() or not source.is_file():
        return value
    target_folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    target = target_folder / f"{digest}_{source.name}"
    if not target.exists():
        shutil.copy2(source, target)
    return os.path.relpath(target, target_root)


def _copy_character(character: dict, source_root: Path, target_root: Path, folder: Path) -> dict:
    cloned = copy.deepcopy(character)
    for field in ("canonical_image", "voice", "sheet"):
        if cloned.get(field):
            cloned[field] = _copy_plan_file(cloned[field], source_root, target_root, folder)
    cloned["voice_refs"] = [
        _copy_plan_file(value, source_root, target_root, folder) for value in cloned.get("voice_refs", [])
    ]
    return cloned


def _copy_result(source_result: dict, source_out: Path, target_out: Path, shot_id: str, scene_id: str) -> dict | None:
    result = copy.deepcopy(source_result)
    target_takes = target_out / "takes"
    target_takes.mkdir(parents=True, exist_ok=True)
    copied = []
    chosen_source = int(result.get("chosen", 0))
    chosen_target = 0
    for i, take in enumerate(result.get("takes", [])):
        source_video = Path(take.get("path", ""))
        source_video = source_video if source_video.is_absolute() else (PROJECT / source_video).resolve()
        if not source_video.exists():
            continue
        stem = f"{shot_id}_import_{i}"
        target_video = target_takes / f"{stem}{source_video.suffix}"
        shutil.copy2(source_video, target_video)
        take["path"] = str(target_video)
        if take.get("dub"):
            source_dub = Path(take["dub"])
            source_dub = source_dub if source_dub.is_absolute() else (PROJECT / source_dub).resolve()
            if source_dub.exists():
                target_dub = target_takes / f"{stem}.dub{source_dub.suffix}"
                shutil.copy2(source_dub, target_dub)
                take["dub"] = str(target_dub)
            else:
                take["dub"] = None
        source_contact = source_out / "contact" / f"{source_video.stem}.png"
        if source_contact.exists():
            target_contact = target_out / "contact" / f"{target_video.stem}.png"
            target_contact.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_contact, target_contact)
        if i == chosen_source:
            chosen_target = len(copied)
        copied.append(take)
    if not copied:
        return None
    result.update(shot=shot_id, scene=scene_id, takes=copied)
    result["chosen"] = chosen_target
    return result


def add_scene(pid: str, mode: str, data: dict) -> str:
    prod, plan_path, raw = _raw_plan(pid)
    existing_scenes = {scene["id"] for scene in raw["scenes"]}
    existing_shots = {shot["id"] for scene in raw["scenes"] for shot in scene["shots"]}
    source_pid = data.get("source_production") or pid
    source_scene_id = data.get("source_scene")
    imported_results: dict[str, dict] = {}

    if mode == "blank":
        scene_id = _unique_id(data.get("name") or data.get("setting") or "scene", existing_scenes)
        scene = {
            "id": scene_id,
            "setting": (data.get("setting") or "A new location").strip(),
            "audio": (data.get("audio") or "Natural ambient sound").strip(),
            "shots": [],
        }
        scene["shots"].append(_new_shot(raw, scene_id, data))
    elif mode in ("duplicate", "import"):
        _, source_plan_path, source_raw = _raw_plan(source_pid)
        source_scene = next((scene for scene in source_raw["scenes"] if scene["id"] == source_scene_id), None)
        if not source_scene:
            raise HTTPException(404, f"no scene {source_scene_id!r} in production {source_pid!r}")
        scene = copy.deepcopy(source_scene)
        scene_id = _unique_id(scene["id"], existing_scenes)
        scene["id"] = scene_id

        character_map: dict[str, str] = {}
        used_characters = {
            value for shot in scene["shots"] for value in (shot.get("character"), shot.get("speaker")) if value
        }
        asset_folder = PRODUCTIONS / pid / "inputs" / "scene_imports" / scene_id
        for character_id in used_characters:
            source_character = source_raw.get("characters", {}).get(character_id)
            if not source_character:
                continue
            target_id = character_id
            if target_id in raw.get("characters", {}) and (
                source_pid != pid or raw["characters"][target_id] != source_character
            ):
                target_id = _unique_id(f"{source_pid}_{character_id}", set(raw.get("characters", {})))
            character_map[character_id] = target_id
            if target_id not in raw.setdefault("characters", {}):
                raw["characters"][target_id] = _copy_character(
                    source_character, source_plan_path.parent, plan_path.parent, asset_folder / "characters"
                )

        prop_map: dict[str, str] = {}
        used_props = {
            name
            for shot in scene["shots"]
            for name in re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", shot.get("action", ""))
        }
        for prop_id in used_props:
            if prop_id not in source_raw.get("props", {}):
                continue
            target_id = prop_id
            if target_id in raw.setdefault("props", {}) and raw["props"][target_id] != source_raw["props"][prop_id]:
                target_id = _unique_id(f"{source_pid}_{prop_id}", set(raw["props"]))
            prop_map[prop_id] = target_id
            raw["props"].setdefault(target_id, source_raw["props"][prop_id])

        source_result_map = _resolved(_path(_read(source_pid)["out"]))
        id_map: dict[str, str] = {}
        for source_shot in scene["shots"]:
            new_id = _unique_id(source_shot["id"], existing_shots | set(id_map.values()))
            id_map[source_shot["id"]] = new_id
            source_shot["id"] = new_id
            for field in ("character", "speaker"):
                if source_shot.get(field) in character_map:
                    source_shot[field] = character_map[source_shot[field]]
            for field in ("image", "end_image"):
                if source_shot.get(field):
                    source_shot[field] = _copy_plan_file(
                        source_shot[field], source_plan_path.parent, plan_path.parent, asset_folder / "references"
                    )
            for old_prop, new_prop in prop_map.items():
                source_shot["action"] = source_shot.get("action", "").replace(
                    "{" + old_prop + "}", "{" + new_prop + "}"
                )
        previous = _previous_last_shot(raw)
        for source_id, shot in zip(id_map, scene["shots"]):
            if shot.get("from") in id_map:
                shot["from"] = id_map[shot["from"]]
            elif shot.get("start") == "continue" and previous:
                shot["from"] = previous
            source_result = source_result_map.get(source_id)
            if data.get("reuse_takes", True) and source_result:
                source_out = _path(_read(source_pid)["out"])
                target_out = _path(prod["out"])
                result = _copy_result(source_result, source_out, target_out, shot["id"], scene_id)
                if result:
                    imported_results[shot["id"]] = result
            previous = shot["id"]
    else:
        raise HTTPException(422, "scene mode must be blank, duplicate or import")

    raw["scenes"].append(scene)
    _repair_continuations(raw)
    _write_plan(pid, raw)
    if imported_results:
        target_out = _path(prod["out"])
        target_out.mkdir(parents=True, exist_ok=True)
        resolved = _resolved(target_out)
        resolved.update(imported_results)
        (target_out / "plan.resolved.json").write_text(json.dumps(resolved, indent=2))
    return scene_id


def reorder_shots(pid: str, scene_id: str, shot_ids: list[str]) -> None:
    prod = _read(pid)
    plan_path = _path(prod.get("plan"))
    if not plan_path:
        raise HTTPException(409, "this production has no shot plan yet")
    raw = json.loads(plan_path.read_text())
    scene = next((s for s in raw["scenes"] if s["id"] == scene_id), None)
    if not scene:
        raise HTTPException(404, f"no scene {scene_id!r}")
    current = [s["id"] for s in scene["shots"]]
    if len(shot_ids) != len(set(shot_ids)) or set(shot_ids) != set(current):
        raise HTTPException(422, "the new order must contain every shot in the scene exactly once")
    by_id = {s["id"]: s for s in scene["shots"]}
    scene["shots"] = [by_id[sid] for sid in shot_ids]
    _repair_continuations(raw)
    _write_plan(pid, raw)


def delete_shot(pid: str, shot_id: str) -> None:
    prod = _read(pid)
    plan_path = _path(prod.get("plan"))
    if not plan_path:
        raise HTTPException(409, "this production has no shot plan yet")
    raw = json.loads(plan_path.read_text())
    found = False
    for scene in raw["scenes"]:
        before = len(scene["shots"])
        scene["shots"] = [s for s in scene["shots"] if s["id"] != shot_id]
        found = found or len(scene["shots"]) != before
    if not found:
        raise HTTPException(404, f"no shot {shot_id!r}")
    raw["scenes"] = [scene for scene in raw["scenes"] if scene["shots"]]
    if not raw["scenes"]:
        raise HTTPException(422, "a production must keep at least one shot")
    _repair_continuations(raw)
    _write_plan(pid, raw)


def _raw_shot(pid: str, shot_id: str) -> tuple[Path, dict, dict]:
    prod = _read(pid)
    plan_path = _path(prod.get("plan"))
    if not plan_path:
        raise HTTPException(409, "this production has no shot plan yet")
    raw = json.loads(plan_path.read_text())
    shot = next((shot for scene in raw["scenes"] for shot in scene["shots"] if shot["id"] == shot_id), None)
    if not shot:
        raise HTTPException(404, f"no shot {shot_id!r}")
    return plan_path, raw, shot


def _previous_shot_id(raw: dict, shot_id: str) -> str | None:
    previous = None
    for scene in raw["scenes"]:
        for shot in scene["shots"]:
            if shot["id"] == shot_id:
                return previous
            previous = shot["id"]
    return None


def _remove_owned_reference(plan_path: Path, value: str | None, owned: Path) -> None:
    """Delete only images created by the shot-reference editor, never planning/keyframe inputs."""
    if not value:
        return
    path = Path(value)
    path = path if path.is_absolute() else (plan_path.parent / path).resolve()
    try:
        path.relative_to(owned.resolve())
    except ValueError:
        return
    path.unlink(missing_ok=True)


def set_shot_reference(pid: str, shot_id: str, edge: str, name: str, data: bytes) -> None:
    if edge not in ("start", "end"):
        raise HTTPException(422, "reference edge must be start or end")
    plan_path, raw, shot = _raw_shot(pid, shot_id)
    field = "image" if edge == "start" else "end_image"
    previous = shot.get(field)
    owned = PRODUCTIONS / pid / "inputs" / "shot_refs"
    owned.mkdir(parents=True, exist_ok=True)
    ext = Path(name).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".png"
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", shot_id).strip("-") or "shot"
    digest = hashlib.sha256(data).hexdigest()[:12]
    path = owned / f"{safe_id}_{edge}_{digest}{ext}"
    created = not path.exists()
    path.write_bytes(data)
    shot[field] = os.path.relpath(path, plan_path.parent)
    if edge == "start":
        shot["start"] = "anchor"
        shot.pop("from", None)
    try:
        _write_plan(pid, raw)
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise
    if previous != shot[field]:
        _remove_owned_reference(plan_path, previous, owned)


def remove_shot_reference(pid: str, shot_id: str, edge: str) -> None:
    if edge not in ("start", "end"):
        raise HTTPException(422, "reference edge must be start or end")
    plan_path, raw, shot = _raw_shot(pid, shot_id)
    field = "image" if edge == "start" else "end_image"
    previous = shot.pop(field, None)
    if not previous:
        return
    if edge == "start" and shot.get("start") == "anchor":
        prior_shot = _previous_shot_id(raw, shot_id)
        if prior_shot:
            shot["start"] = "continue"
            shot["from"] = prior_shot
        else:
            shot["start"] = "fresh"
            shot.pop("from", None)
    _write_plan(pid, raw)
    _remove_owned_reference(plan_path, previous, PRODUCTIONS / pid / "inputs" / "shot_refs")


def set_neighbor_reference(pid: str, shot_id: str, edge: str) -> None:
    """Copy the adjacent chosen take's boundary frame into this shot's editable references."""
    if edge not in ("start", "end"):
        raise HTTPException(422, "reference edge must be start or end")
    _, raw, _ = _raw_shot(pid, shot_id)
    ids = [shot["id"] for scene in raw["scenes"] for shot in scene["shots"]]
    index = ids.index(shot_id)
    neighbor_index = index - 1 if edge == "start" else index + 1
    if neighbor_index < 0 or neighbor_index >= len(ids):
        label = "previous" if edge == "start" else "next"
        raise HTTPException(422, f"this shot has no {label} shot")
    neighbor_id = ids[neighbor_index]
    prod = _read(pid)
    out = _path(prod.get("out"))
    resolved = _resolved(out)
    result = resolved.get(neighbor_id)
    if not result or result.get("chosen") is None:
        raise HTTPException(409, f"render {neighbor_id} before using one of its frames")
    try:
        source = Path(result["takes"][result["chosen"]]["path"])
    except (IndexError, KeyError, TypeError):
        raise HTTPException(409, f"the chosen take for {neighbor_id} is unavailable") from None
    source = source if source.is_absolute() else (PROJECT / source).resolve()
    if not source.exists():
        raise HTTPException(409, f"the chosen take for {neighbor_id} is unavailable")
    boundary = "last" if edge == "start" else "first"
    with tempfile.TemporaryDirectory() as folder:
        frame = Path(folder) / f"{neighbor_id}_{boundary}.png"
        (last_frame if edge == "start" else first_frame)(source, frame)
        set_shot_reference(pid, shot_id, edge, frame.name, frame.read_bytes())


def all_ids() -> list[str]:
    if not PRODUCTIONS.exists():
        return []
    return sorted(p.name for p in PRODUCTIONS.iterdir() if (p / "production.json").exists())


# ---------------------------------------------------------------- detail


def _resolved(out: Path | None) -> dict:
    f = out / "plan.resolved.json" if out else None
    return json.loads(f.read_text()) if f and f.exists() else {}


def choose_audio(pid: str, sid: str, source: str) -> None:
    plan_path, out = plan_and_out(pid)
    if source not in ("cast", "original"):
        raise HTTPException(422, "audio source must be cast or original")
    plan = load_plan(plan_path) if plan_path else None
    shot = next((s for s in plan.shots() if s.id == sid), None) if plan else None
    if not shot:
        raise HTTPException(404, "no such shot")
    if sid not in _resolved(out):
        raise HTTPException(409, "render the shot before choosing its audio")
    if source == "cast" and not (plan.dubbed and shot.line):
        raise HTTPException(422, "this shot has no cast voice")
    save_choice(out, sid, source)


def _action(plan, shot) -> str:
    """A shot's action as people read it: older plans hold prop descriptions as full sentences ("A sleek …
    palette."), which read oddly inside an action, so the article and the full stop are dropped here."""
    props = {k: re.sub(r"^(a|an|the)\s+", "", v.strip().rstrip("."), flags=re.I) for k, v in plan.props.items()}
    return shot.action.format(**props)


def _take_view(take: dict, out: Path) -> dict:
    path = Path(take["path"])
    contact = out / "contact" / f"{path.stem}.png"
    return {
        **{k: take.get(k) for k in ("index", "seed", "render_s", "cached", "seconds", "heard", "wer", "voice",
                                     "identity", "continuity", "heads", "failures", "passed", "speaker",
                                     "speaker_note", "dub_words", "edit_prompt", "audio_prompt")},
        "path": to_virtual(path),
        "dub": to_virtual(Path(take["dub"])) if take.get("dub") and Path(take["dub"]).exists() else None,
        "dub_revision": Path(take["dub"]).stat().st_mtime_ns if take.get("dub") and Path(take["dub"]).exists() else None,
        "contact": to_virtual(contact) if contact.exists() else None,
    }  # fmt: skip


def _live_state(events: list[dict]) -> dict:
    """Per-shot live status from the latest run's events."""
    live: dict[str, dict] = {}
    for e in events:
        shot = e.get("shot")
        if e["type"] == "take_started":
            live.setdefault(shot, {"takes": []})
            live[shot].update(status="rendering", current_take=e["take"])
        elif e["type"] == "take_done":
            live.setdefault(shot, {"takes": []})["takes"].append(e)
            live[shot]["status"] = "checking"
        elif e["type"] == "shot_done":
            live.setdefault(shot, {"takes": []}).update(
                status="needs_review" if e["needs_review"] else "done", chosen=e["chosen"]
            )
    return live


def progress(events: list[dict]) -> dict | None:
    if not events:
        return None
    run = events[0]
    total = len(run.get("shots", []))
    done = [e for e in events if e["type"] == "shot_done"]
    takes = [e for e in events if e["type"] == "take_done"]
    renders = [t for t in takes if not t.get("cached")]
    phase = next((e["name"] for e in reversed(events) if e["type"] == "phase"), "starting")
    current = next((e for e in reversed(events) if e["type"] in ("take_started", "take_done", "shot_done")), None)
    avg = sum(t["render_s"] for t in renders) / len(renders) if renders else None
    takes_per_shot = len(takes) / len(done) if done else 1.5
    remaining = max(0, total - len(done))
    finished = next((e for e in reversed(events) if e["type"] in ("film_done", "run_failed")), None)
    return {
        "phase": "finished" if finished and finished["type"] == "film_done" else
                 "failed" if finished else phase,
        "shots_total": total,
        "shots_done": len(done),
        "takes_done": len(takes),
        "renders_done": len(renders),
        "render_s_total": round(sum(t["render_s"] for t in renders), 1),
        "current_shot": current.get("shot") if current and current["type"] == "take_started" else None,
        "current_take": current.get("take") if current and current["type"] == "take_started" else None,
        "eta_s": round(remaining * takes_per_shot * avg + 15) if avg and remaining and not finished else None,
        "started": run["t"],
        "last_event": events[-1]["t"],
        "error": finished.get("error") if finished and finished["type"] == "run_failed" else None,
    }  # fmt: skip


def _film(out: Path | None, plan, resolved: dict) -> dict | None:
    film = out / "final.mp4" if out else None
    if not film or not film.exists():
        return None
    markers, t = [], 0.0
    for shot in plan.shots() if plan else []:
        res = resolved.get(shot.id)
        if not res:
            continue
        seconds = res["takes"][res["chosen"]]["seconds"] - (1 / FPS if shot.start == "continue" else 0)
        markers.append({"shot": shot.id, "scene": shot.scene_id, "start": round(t, 3), "end": round(t + seconds, 3),
                        "label": shot.line or _action(plan, shot).split(".")[0]})  # fmt: skip
        t += seconds
    edit = load_edit(out)
    choices = load_choices(out)
    sources = {s.id: audio_source(plan, s, choices) for s in plan.shots()} if plan else {}
    previous = edit.get("audio_sources", {s.id: audio_source(plan, s, {}) for s in plan.shots()} if plan else {})
    return {"path": to_virtual(film), "duration": media_duration(film), "markers": edit.get("markers", markers),
            "revision": film.stat().st_mtime_ns, "audio_pending": sources != previous,
            "audio_upgrade": "cast" in sources.values() and edit.get("dub_version", 0) != DUB_VERSION,
            "report": (out / "report.md").read_text() if (out / "report.md").exists() else None}  # fmt: skip


def _vpath(rel: str | None) -> str | None:
    return to_virtual(PROJECT / rel) if rel else None


def _preprod_view(pid: str) -> dict | None:
    d = PRODUCTIONS / pid / "preprod"
    if not d.exists():
        return None

    def load(name: str):
        f = d / f"{name}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def frames(entry: dict) -> dict:
        return {"chosen": entry.get("chosen"), "candidates": [{**c, "frame": _vpath(c["frame"])} for c in entry.get("candidates", [])]}

    kf = load("keyframes")
    if kf:
        kf = {
            "sheets": {k: _vpath(v) for k, v in kf.get("sheets", {}).items()},
            "props": {k: _vpath(v) for k, v in kf.get("props", {}).items()},
            "scenes": {sid: {**frames(sc), "singles": {cid: frames(e) for cid, e in sc.get("singles", {}).items()}}
                       for sid, sc in kf.get("scenes", {}).items()},
        }  # fmt: skip
    voice = load("voice")  # an LTX voice audition, from before voice casting
    if voice:
        voice = {**voice, "clips": [{**c, "video": _vpath(c["video"]), "audio": _vpath(c["audio"])} for c in voice["clips"]]}
    voices = load("voices")  # cast voices: per character, every candidate and the chosen one
    if voices:
        voices = {cid: {"chosen": v.get("chosen"), "candidates": [{**c, "path": _vpath(c["path"])} for c in v["candidates"]]}
                  for cid, v in voices.items()}  # fmt: skip
    run = latest_run(d)
    said = [e for e in run if e["type"] in ("agent_message", "run_failed", "run_finished")]
    trace = [e for e in run if e["type"] in ("trace", "run_started", "run_failed", "run_finished")]
    summary_file = d / "director_summary.md"
    return {
        "frame": load("frame"),
        "cast": load("cast"),
        "screenplay": load("screenplay"),
        "keyframes": kf,
        "voice": voice,
        "voices": voices,
        "summary": summary_file.read_text() if summary_file.exists() else None,
        "conversation": said[-80:],
        "trace": trace[-800:],
    }


def _active(pid: str, jobs: list[dict]) -> dict | None:
    return next((j for j in jobs if j["production"] == pid and j["status"] in ("queued", "running", "cancelling")), None)


def _job_progress(active: dict | None, out: Path | None, pid: str) -> dict | None:
    if not active:
        return None
    if active.get("kind", "render") in ("render", "export", "clip", "overlay"):
        return progress(latest_run(out)) if out and out.exists() else None
    folder = PRODUCTIONS / pid / "preprod" / ("voice" if active.get("kind") == "audition" else "")
    events = latest_run(folder)
    return progress(events) if active.get("kind") == "audition" else agent_progress(events)


def summary(pid: str, jobs: list[dict]) -> dict:
    prod = _read(pid)
    out = _path(prod["out"])
    resolved = _resolved(out)
    active = _active(pid, jobs)
    film = out / "final.mp4" if out else None
    takes = [t for r in resolved.values() for t in r["takes"]]
    return {
        **{k: prod[k] for k in ("id", "title", "created", "updated", "source", "target_seconds", "steps")},
        "first_frame": to_virtual(_path(prod["first_frame"])),
        "reference_images": [
            {**ref, "path": to_virtual(_path(ref["path"]))}
            for ref in prod.get("reference_images", [
                {"role": "opening", "name": Path(prod["first_frame"]).name, "path": prod["first_frame"]}
            ])
        ],
        "poster": to_virtual(film) if film and film.exists() else None,
        "film_seconds": media_duration(film) if film and film.exists() else None,
        "shots_done": len(resolved),
        "takes": len(takes),
        "active_job": active,
        "progress": _job_progress(active, out, pid),
    }


def detail(pid: str, jobs: list[dict]) -> dict:
    prod = _read(pid)
    out = _path(prod["out"])
    plan = load_plan(_path(prod["plan"])) if prod.get("plan") else None
    resolved = _resolved(out)
    events = latest_run(out) if out and out.exists() else []
    active = _active(pid, jobs)
    rendering = bool(active) and active.get("kind", "render") in ("render", "clip")
    editing = bool(active) and active.get("kind") in ("export", "overlay")
    choices = load_choices(out) if out else {}
    live = _live_state(events) if rendering else {}

    scenes = []
    for scene in plan.scenes if plan else []:
        shots = []
        for shot in scene.shots:
            res = resolved.get(shot.id)  # the last complete run
            now = live.get(shot.id)  # the running job, once it has reached this shot
            if now:
                takes = [_take_view(t, out) for t in now["takes"]]
                status, chosen = now.get("status", "rendering"), now.get("chosen")
            elif res:
                takes = [_take_view(t, out) for t in res["takes"]]
                status, chosen = ("needs_review" if res["needs_review"] else "done"), res["chosen"]
            else:
                takes, status, chosen = [], "pending", None
            shots.append({
                "id": shot.id, "start": shot.start, "from": shot.from_shot,
                "image": to_virtual(shot.image) if shot.image else None,
                "end_image": to_virtual(shot.end_image) if shot.end_image else None,
                "character": shot.character, "line": shot.line, "action": _action(plan, shot),
                "speaker": shot.speaker, "delivery": shot.delivery,
                "audio_source": audio_source(plan, shot, choices),
                "has_cast_audio": bool(plan.dubbed and shot.line),
                "camera": shot.camera, "seconds": shot.seconds, "identity_check": shot.identity_check,
                "takes_planned": shot.takes, "status": status,
                "current_take": now.get("current_take") if now else None,
                "takes": takes, "chosen": chosen,
                "prompt": res["prompt"] if res else None,
            })  # fmt: skip
        scenes.append({"id": scene.id, "setting": scene.setting, "audio": scene.audio, "shots": shots})

    characters = [
        {"id": c.id, "bible": c.bible, "voice_phrase": c.voice_phrase, "image": to_virtual(c.canonical_image),
         "voice_refs": len(c.voice_refs)}
        for c in (plan.characters.values() if plan else [])
    ]  # fmt: skip
    steps = dict(prod["steps"])
    if rendering:
        steps["render"] = "running" if active["status"] != "queued" else "queued"
    if editing:
        steps["assemble"] = "running" if active["status"] != "queued" else "queued"
    stages = [{**stage, "status": steps.get(stage["key"], "pending")} for stage in STAGES]
    if prod.get("story_mode") == "ai":
        story_stage = next(stage for stage in stages if stage["key"] == "story")
        story_stage.update({
            "owner": "Storyteller",
            "engine": VISION_ENGINE if prod.get("story_uses_images") else LLM_ENGINE,
            "model": VISION_MODEL if prod.get("story_uses_images") else LLM_MODEL,
            "detail": prod.get("story_note") or "Invented the title and story from the creative direction",
        })
    return {
        **summary(pid, jobs),
        "story": prod["story"],
        "story_mode": prod.get("story_mode", "manual"),
        "story_prompt": prod.get("story_prompt"),
        "story_uses_images": prod.get("story_uses_images"),
        "story_note": prod.get("story_note"),
        "stages": stages,
        "characters": characters,
        "props": plan.props if plan else {},
        "scenes": scenes,
        "film": _film(out, plan, resolved),
        "out": to_virtual(out) if out and out.exists() else None,
        "progress": progress(events) if not active or rendering or editing else None,
        "agent_progress": _job_progress(active, out, pid) if active and not (rendering or editing) else None,
        "preprod": _preprod_view(pid),
        "jobs": [j for j in jobs if j["production"] == pid],
        "can_render": bool(plan) and not active and ready_to_render(pid),
        "can_plan": not active and prod.get("source") == "Uploaded",
        "can_audition": bool(plan) and not active and steps.get("voice") in ("pending", "awaiting_approval", "failed")
        and not (PRODUCTIONS / pid / "preprod" / "voices.json").exists(),  # cast voices replace the LTX audition
    }


def plan_and_out(pid: str) -> tuple[Path | None, Path]:
    prod = _read(pid)
    return _path(prod.get("plan")), _path(prod["out"])
