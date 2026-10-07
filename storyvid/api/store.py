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
    {"key": "keyframes", "label": "Coverage keyframes", "owner": "KeyframeArtist", "engine": "openai",
     "model": OPENAI_IMAGE_MODEL or "OpenAI image model", "checkpoint": True,
     "detail": "Per scene: an establishing frame and a close-up of everyone who speaks, reviewed against the sheets"},
    {"key": "voice", "label": "Voice casting", "owner": "CastingDirector", "engine": "qwen",
     "model": "Qwen3-TTS VoiceDesign (local)", "checkpoint": True,
     "detail": "Each speaking character's voice, designed once; every line is spoken in it"},
    {"key": "render", "label": "Render & QA", "owner": "ProductionManager", "engine": "ltx",
     "model": "LTX-2.5 (local)",
     "detail": "Every take checked: the words, who is talking (Claude), and the cast voice timed to the lips"},
    {"key": "assemble", "label": "Edit", "owner": "Editor", "engine": "ffmpeg", "model": "ffmpeg",
     "detail": "Cut, fades, scene ambience under the voices, loudness"},
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
                                     "speaker_note", "dub_words")},
        "path": to_virtual(path),
        "dub": to_virtual(Path(take["dub"])) if take.get("dub") and Path(take["dub"]).exists() else None,
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
    return {"path": to_virtual(film), "duration": media_duration(film), "markers": markers,
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
    if active.get("kind", "render") == "render":
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
    rendering = bool(active) and active.get("kind", "render") == "render"
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
                "character": shot.character, "line": shot.line, "action": _action(plan, shot),
                "speaker": shot.speaker, "delivery": shot.delivery,
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
    return {
        **summary(pid, jobs),
        "story": prod["story"],
        "stages": [{**s, "status": steps.get(s["key"], "pending")} for s in STAGES],
        "characters": characters,
        "props": plan.props if plan else {},
        "scenes": scenes,
        "film": _film(out, plan, resolved),
        "out": to_virtual(out) if out and out.exists() else None,
        "progress": progress(events) if not active or rendering else None,
        "agent_progress": _job_progress(active, out, pid) if active and not rendering else None,
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
