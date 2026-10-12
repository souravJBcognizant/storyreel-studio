"""Storyreel studio API.

Run (dev):  uv run uvicorn storyvid.api.app:app --port 8787 --reload
The React app (web/) proxies /api and /media here; a production build is served from web/dist.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..events import latest_run
from ..story_draft import generate_story
from . import agentnet, files, store
from .config import PROJECT, settings
from .jobs import JobManager

MAX_FRAME_BYTES = 25 * 1024 * 1024
MAX_GUIDE_FRAMES = 6
jobs = JobManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.ensure_imports()
    jobs.start()
    yield
    jobs.stop()


app = FastAPI(title="Storyreel studio", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return settings()


# ------------------------------------------------------------ productions


@app.get("/api/productions")
def list_productions():
    all_jobs = jobs.all()
    items = [store.summary(pid, all_jobs) for pid in store.all_ids()]
    return sorted(items, key=lambda p: p["updated"], reverse=True)


@app.post("/api/productions")
async def create_production(
    title: str = Form(""),
    story: str = Form(""),
    story_mode: Literal["manual", "ai"] = Form("manual"),
    story_prompt: str = Form(""),
    target_seconds: int = Form(60),
    first_frame: UploadFile = File(...),
    guide_frames: list[UploadFile] = File(default=[]),
    final_frame: UploadFile | None = File(default=None),
):
    if len(guide_frames) > MAX_GUIDE_FRAMES:
        raise HTTPException(422, f"add at most {MAX_GUIDE_FRAMES} guide frames")

    async def read_image(upload: UploadFile, label: str) -> tuple[str, bytes]:
        if not (upload.content_type or "").startswith("image/"):
            raise HTTPException(422, f"the {label} must be an image")
        data = await upload.read()
        if len(data) > MAX_FRAME_BYTES:
            raise HTTPException(413, f"the {label} is larger than 25 MB")
        return upload.filename or f"{label.replace(' ', '_')}.png", data

    opening = await read_image(first_frame, "opening frame")
    guides = [await read_image(upload, f"guide frame {i}") for i, upload in enumerate(guide_frames, 1)]
    ending = await read_image(final_frame, "final frame") if final_frame else None
    story_uses_images = story_note = None
    if story_mode == "ai":
        if len(story_prompt.strip()) > 1200:
            raise HTTPException(422, "keep the creative direction under 1,200 characters")
        references = [("opening", opening[0], opening[1])]
        references += [("guide", name, data) for name, data in guides]
        if ending:
            references.append(("ending", ending[0], ending[1]))
        try:
            generated = await asyncio.to_thread(generate_story, story_prompt, target_seconds, references)
        except Exception as exc:
            raise HTTPException(502, f"the AI could not invent the story: {exc}") from exc
        title, story = generated.title, generated.story
        story_uses_images, story_note = generated.used_images, generated.note
    elif not title.strip() or len(story.strip()) < 20:
        raise HTTPException(422, "a title and a story of at least a couple of sentences are needed")
    prod = store.create(
        title, story, *opening, target_seconds, guide_frames=guides, final_frame=ending,
        story_mode=story_mode, story_prompt=story_prompt.strip() or None,
        story_uses_images=story_uses_images, story_note=story_note,
    )
    return store.detail(prod["id"], jobs.all())


@app.get("/api/productions/{pid}")
def get_production(pid: str):
    return store.detail(pid, jobs.all())


@app.delete("/api/productions/{pid}")
def delete_production(pid: str):
    if any(j["production"] == pid and j["status"] in ("queued", "running", "cancelling") for j in jobs.all()):
        raise HTTPException(409, "cancel the running job first")
    store.delete(pid)
    return {"deleted": pid}


@app.post("/api/productions/{pid}/approve")
def approve(pid: str, stage: str):
    store.approve(pid, stage)
    return store.detail(pid, jobs.all())


@app.post("/api/productions/{pid}/jobs")
def start_job(pid: str, kind: str = "render"):
    return jobs.submit(pid, kind)


class AudioChoice(BaseModel):
    source: Literal["cast", "original"]


class DuplicateProduction(BaseModel):
    title: str


@app.post("/api/productions/{pid}/duplicate")
def duplicate_production(pid: str, body: DuplicateProduction):
    if any(j["production"] == pid and j["status"] in ("queued", "running", "cancelling") for j in jobs.all()):
        raise HTTPException(409, "wait for the source production's current job to finish")
    prod = store.duplicate(pid, body.title)
    return store.detail(prod["id"], jobs.all())


@app.put("/api/productions/{pid}/shots/{sid}/audio")
def choose_audio(pid: str, sid: str, body: AudioChoice):
    jobs.choose_audio(pid, sid, body.source)
    return store.detail(pid, jobs.all())


class EditPrompt(BaseModel):
    prompt: str


class ShotOrder(BaseModel):
    shot_ids: list[str]


def ensure_idle(pid: str) -> None:
    if any(j["production"] == pid and j["status"] in ("queued", "running", "cancelling") for j in jobs.all()):
        raise HTTPException(409, "wait for the current job to finish before editing the timeline")


@app.put("/api/productions/{pid}/scenes/{scene_id}/shots/order")
def reorder_shots(pid: str, scene_id: str, body: ShotOrder):
    ensure_idle(pid)
    store.reorder_shots(pid, scene_id, body.shot_ids)
    return store.detail(pid, jobs.all())


@app.delete("/api/productions/{pid}/shots/{sid}")
def delete_shot(pid: str, sid: str):
    ensure_idle(pid)
    store.delete_shot(pid, sid)
    return store.detail(pid, jobs.all())


@app.put("/api/productions/{pid}/shots/{sid}/references/{edge}")
async def set_shot_reference(pid: str, sid: str, edge: Literal["start", "end"], frame: UploadFile = File(...)):
    ensure_idle(pid)
    if not (frame.content_type or "").startswith("image/"):
        raise HTTPException(422, "the clip reference must be an image")
    data = await frame.read()
    if len(data) > MAX_FRAME_BYTES:
        raise HTTPException(413, "the clip reference is larger than 25 MB")
    store.set_shot_reference(pid, sid, edge, frame.filename or f"{edge}_reference.png", data)
    return store.detail(pid, jobs.all())


@app.delete("/api/productions/{pid}/shots/{sid}/references/{edge}")
def remove_shot_reference(pid: str, sid: str, edge: Literal["start", "end"]):
    ensure_idle(pid)
    store.remove_shot_reference(pid, sid, edge)
    return store.detail(pid, jobs.all())


@app.put("/api/productions/{pid}/shots/{sid}/references/{edge}/neighbor")
def set_neighbor_reference(pid: str, sid: str, edge: Literal["start", "end"]):
    ensure_idle(pid)
    store.set_neighbor_reference(pid, sid, edge)
    return store.detail(pid, jobs.all())


@app.post("/api/productions/{pid}/shots/{sid}/regenerate")
def regenerate_shot(pid: str, sid: str, body: EditPrompt):
    """Generate a new take from a human direction and rebuild the finished film."""
    return jobs.submit(pid, "clip", shot=sid, prompt=body.prompt)


@app.post("/api/productions/{pid}/shots/{sid}/regenerate-overlay")
def regenerate_overlay(pid: str, sid: str, body: EditPrompt):
    """Generate a directed delivery for the scripted line, align it, and rebuild the film."""
    return jobs.submit(pid, "overlay", shot=sid, prompt=body.prompt)


class Recast(BaseModel):
    description: str
    text: str


@app.post("/api/productions/{pid}/voices/{cid}/recast")
def recast_voice(pid: str, cid: str, body: Recast):
    """Design a new voice for one character from an edited description (a short job: about 20 s)."""
    if not body.description.strip() or len(body.text.split()) < 8:
        raise HTTPException(400, "describe the voice, and give a reference text of at least 8 words")
    folder = store.preprod_dir(pid) / "voices"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"recast_{cid}.json").write_text(json.dumps({"description": body.description.strip(), "text": body.text.strip()}))
    return jobs.submit(pid, "casting", character=cid)


@app.post("/api/productions/{pid}/voices/{cid}/choose")
def choose_voice(pid: str, cid: str, n: int):
    from ..casting import choose_voice

    try:
        choose_voice(pid, cid, n)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return store.detail(pid, jobs.all())


@app.get("/api/agents/network")
def agent_network():
    return agentnet.network()


# ------------------------------------------------------------ jobs


@app.get("/api/jobs")
def list_jobs():
    return jobs.all()


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = jobs.get(jid)
    events = latest_run(PROJECT / job["out"]) if job["status"] in ("running", "cancelling") else []
    if not events:
        return {**job, "progress": job.get("summary")}
    progress = store.agent_progress(events) if job.get("kind") == "preprod" else store.progress(events)
    return {**job, "progress": progress}


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    return jobs.cancel(jid)


@app.get("/api/jobs/{jid}/log", response_class=PlainTextResponse)
def job_log(jid: str, lines: int = 200):
    return "\n".join(jobs.log_tail(jid, lines))


@app.get("/api/jobs/{jid}/events")
def job_events(jid: str):
    return latest_run(PROJECT / jobs.get(jid)["out"])


# ------------------------------------------------------------ files & media


@app.get("/api/files/roots")
def file_roots():
    return files.roots()


@app.get("/api/files")
def list_files(path: str):
    return files.listing(path)


@app.get("/api/thumb")
def thumb(path: str, at: float = 1.0, w: int = 480):
    return FileResponse(files.thumbnail(path, at, min(max(w, 64), 1280)), media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"})  # fmt: skip


@app.get("/api/text", response_class=PlainTextResponse)
def text_file(path: str, max_bytes: int = 200_000):
    f = files.resolve(path)
    if files.kind_of(f) != "text":
        raise HTTPException(400, "not a text file")
    return f.read_bytes()[:max_bytes].decode("utf-8", errors="replace")


@app.get("/media/{vpath:path}")
def media(vpath: str):
    f = files.resolve(vpath)
    if f.is_dir():
        raise HTTPException(400, "is a directory")
    return FileResponse(f, media_type=files.media_type(f))  # Starlette serves Range requests (seeking)


# ------------------------------------------------------------ the built React app

DIST = PROJECT / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def spa(spa_path: str):
        f = (DIST / spa_path).resolve()
        if spa_path and DIST in f.parents and f.is_file():
            return FileResponse(f)
        return FileResponse(Path(DIST / "index.html"))
