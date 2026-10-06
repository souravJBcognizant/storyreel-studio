"""Productions on disk: one folder per film under productions/, described by production.json.

A production's detail joins four sources: production.json (inputs and stage states), the plan,
the pipeline's plan.resolved.json (finished shots) and events.jsonl (what is happening right now).
"""

import json
import re
import shutil
import time
from pathlib import Path

from fastapi import HTTPException

from ..events import latest_run
from ..plan import load_plan
from .config import CLAUDE_MODEL, CLAUDE_MODEL_ROUTINE, OPENAI_IMAGE_MODEL, PRODUCTIONS, PROJECT
from .files import media_duration, to_virtual

FPS = 24

# The full pipeline, in order. `checkpoint` stages wait for the user's approval.
STAGES = [
    {"key": "story", "label": "Story & first frame", "owner": "You", "engine": "user",
     "detail": "Upload the opening frame and write the story"},
    {"key": "analysis", "label": "Story analysis", "owner": "StoryAnalyst", "engine": "claude", "model": CLAUDE_MODEL,
     "detail": "Reads the story and the first frame: characters, look, voice, tone"},
    {"key": "plan", "label": "Screenplay & shots", "owner": "Screenwriter · ShotPlanner", "engine": "claude",
     "model": CLAUDE_MODEL, "checkpoint": True, "detail": "Scenes, dialogue and a shot plan you approve"},
    {"key": "sheets", "label": "Character & prop sheets", "owner": "KeyframeArtist", "engine": "openai",
     "model": OPENAI_IMAGE_MODEL or "OpenAI image model", "detail": "Reference sheets that lock the look"},
    {"key": "keyframes", "label": "Scene keyframes", "owner": "KeyframeArtist", "engine": "openai",
     "model": OPENAI_IMAGE_MODEL or "OpenAI image model", "checkpoint": True,
     "detail": "One consistent opening frame per scene, identity-checked"},
    {"key": "voice", "label": "Voice audition", "owner": "CastingDirector", "engine": "ltx",
     "model": "LTX-2.5 joint audio", "checkpoint": True, "detail": "Test lines in the character's voice"},
    {"key": "render", "label": "Render & QA", "owner": "ProductionManager", "engine": "ltx",
     "model": "LTX-2.5 (local)", "detail": "Every take checked for words, voice, identity and continuity"},
    {"key": "assemble", "label": "Edit", "owner": "Editor", "engine": "ffmpeg", "model": "ffmpeg",
     "detail": "Cut, fades and loudness"},
    {"key": "film", "label": "Film", "owner": "You", "engine": "user", "detail": "Watch, download, share"},
]
ROUTINE_MODEL = CLAUDE_MODEL_ROUTINE


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


def ensure_imports() -> None:
    """Register the Stage 1 film as the first production (its files stay where they are)."""
    pid = "elios-first-flight"
    if (PRODUCTIONS / pid / "production.json").exists() or not (PROJECT / "stage1" / "plan.json").exists():
        return
    _write({
        "id": pid,
        "title": "Elio's First Flight",
        "created": (PROJECT / "stage1" / "plan.json").stat().st_mtime,
        "updated": time.time(),
        "source": "Stage 1 test (hand-written plan)",
        "story": (
            "Late at night in his cluttered workshop, Elio, a young inventor, finishes a small homemade "
            "flying machine. At golden hour he carries it to the beach, counts down nervously and watches it "
            "lift off. From a cliff at sunset he watches it circle away into the sky."
        ),
        "first_frame": "stage0/out/ltx/character_ref.png",
        "plan": "stage1/plan.json",
        "out": "stage1/out/elio",
        "target_seconds": 30,
        "steps": {"story": "done", "analysis": "skipped", "plan": "done", "sheets": "skipped",
                  "keyframes": "skipped", "voice": "done", "render": "done", "assemble": "done", "film": "done"},
    })  # fmt: skip


def create(title: str, story: str, frame_name: str, frame_bytes: bytes, target_seconds: int) -> dict:
    pid = slugify(title)
    inputs = PRODUCTIONS / pid / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    ext = Path(frame_name).suffix.lower() or ".png"
    (inputs / f"first_frame{ext}").write_bytes(frame_bytes)
    (inputs / "story.md").write_text(story)
    now = time.time()
    prod = {
        "id": pid,
        "title": title.strip(),
        "created": now,
        "updated": now,
        "source": "Uploaded",
        "story": story,
        "first_frame": f"productions/{pid}/inputs/first_frame{ext}",
        "plan": None,
        "out": f"productions/{pid}/out",
        "target_seconds": target_seconds,
        "steps": {s["key"]: "pending" for s in STAGES} | {"story": "done"},
    }
    _write(prod)
    return prod


def delete(pid: str) -> None:
    prod = _read(pid)
    if prod.get("source", "").startswith("Stage"):
        raise HTTPException(400, "imported test productions can't be deleted from the app")
    shutil.rmtree(PRODUCTIONS / pid)


def all_ids() -> list[str]:
    if not PRODUCTIONS.exists():
        return []
    return sorted(p.name for p in PRODUCTIONS.iterdir() if (p / "production.json").exists())


# ---------------------------------------------------------------- detail


def _resolved(out: Path | None) -> dict:
    f = out / "plan.resolved.json" if out else None
    return json.loads(f.read_text()) if f and f.exists() else {}


def _take_view(take: dict, out: Path) -> dict:
    path = Path(take["path"])
    contact = out / "contact" / f"{path.stem}.png"
    return {
        **{k: take.get(k) for k in ("index", "seed", "render_s", "cached", "seconds", "heard", "wer", "voice",
                                     "identity", "continuity", "heads", "failures", "passed")},
        "path": to_virtual(path),
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
                        "label": shot.line or shot.action.format(**plan.props).split(".")[0]})  # fmt: skip
        t += seconds
    return {"path": to_virtual(film), "duration": media_duration(film), "markers": markers,
            "report": (out / "report.md").read_text() if (out / "report.md").exists() else None}  # fmt: skip


def summary(pid: str, jobs: list[dict]) -> dict:
    prod = _read(pid)
    out = _path(prod["out"])
    resolved = _resolved(out)
    events = latest_run(out) if out and out.exists() else []
    active = next((j for j in jobs if j["production"] == pid and j["status"] in ("queued", "running", "cancelling")), None)
    film = out / "final.mp4" if out else None
    takes = [t for r in resolved.values() for t in r["takes"]]
    return {
        **{k: prod[k] for k in ("id", "title", "created", "updated", "source", "target_seconds", "steps")},
        "first_frame": to_virtual(_path(prod["first_frame"])),
        "poster": to_virtual(film) if film and film.exists() else None,
        "film_seconds": media_duration(film) if film and film.exists() else None,
        "shots_done": len(resolved),
        "takes": len(takes),
        "active_job": active,
        "progress": progress(events) if active else None,
    }


def detail(pid: str, jobs: list[dict]) -> dict:
    prod = _read(pid)
    out = _path(prod["out"])
    plan = load_plan(_path(prod["plan"])) if prod.get("plan") else None
    resolved = _resolved(out)
    events = latest_run(out) if out and out.exists() else []
    active = next((j for j in jobs if j["production"] == pid and j["status"] in ("queued", "running", "cancelling")), None)
    live = _live_state(events) if active else {}

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
                "character": shot.character, "line": shot.line, "action": shot.action.format(**plan.props),
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
    if active:
        steps["render"] = "running" if active["status"] != "queued" else "queued"
    return {
        **summary(pid, jobs),
        "story": prod["story"],
        "stages": [{**s, "status": steps.get(s["key"], "pending")} for s in STAGES],
        "characters": characters,
        "props": plan.props if plan else {},
        "scenes": scenes,
        "film": _film(out, plan, resolved),
        "out": to_virtual(out) if out and out.exists() else None,
        "progress": progress(events),
        "jobs": [j for j in jobs if j["production"] == pid],
        "can_render": bool(plan) and not active,
    }


def plan_and_out(pid: str) -> tuple[Path | None, Path]:
    prod = _read(pid)
    return _path(prod.get("plan")), _path(prod["out"])
