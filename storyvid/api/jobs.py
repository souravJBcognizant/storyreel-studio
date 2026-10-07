"""Production jobs: durable, one at a time (one GPU), and independent of the API process.

A job is a JSON file in productions/<id>/jobs/. The render runs as its own process group, so
restarting the API never kills a render; on startup the manager re-attaches by pid. Because
renders are cached by input hash, re-running a failed or cancelled job resumes it.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

from ..events import latest_run
from . import store
from .config import PRODUCTIONS, PROJECT

ACTIVE = ("queued", "running", "cancelling")
KINDS = ("render", "preprod", "audition", "casting")
FINISHED = {"render": "film_done", "preprod": "run_finished", "audition": "run_finished", "casting": "run_finished"}


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class JobManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._jobs: dict[str, dict] = {}
        self._stop = threading.Event()
        self._load()

    # ------------------------------------------------------------ persistence

    def _file(self, job: dict) -> Path:
        return PRODUCTIONS / job["production"] / "jobs" / f"{job['id']}.json"

    def _save(self, job: dict) -> None:
        f = self._file(job)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, indent=2))
        tmp.replace(f)

    def _load(self) -> None:
        for f in PRODUCTIONS.glob("*/jobs/*.json") if PRODUCTIONS.exists() else []:
            job = json.loads(f.read_text())
            self._jobs[job["id"]] = job

    # ------------------------------------------------------------ public

    def all(self) -> list[dict]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs.values()), key=lambda j: j["created"], reverse=True)

    def get(self, jid: str) -> dict:
        with self._lock:
            if jid not in self._jobs:
                raise HTTPException(404, "no such job")
            return dict(self._jobs[jid])

    def submit(self, pid: str, kind: str = "render", character: str | None = None) -> dict:
        plan, out = store.plan_and_out(pid)
        if kind not in KINDS:
            raise HTTPException(400, f"unknown job kind {kind!r}")
        if kind in ("render", "audition") and (not plan or not plan.exists()):
            raise HTTPException(409, "this production has no shot plan yet")
        if kind == "render" and not store.ready_to_render(pid):
            raise HTTPException(409, "approve the plan, keyframes and voice before rendering")
        if kind == "casting" and not character:
            raise HTTPException(400, "a recast needs the character")
        work = {"render": out, "preprod": store.preprod_dir(pid), "audition": store.preprod_dir(pid) / "voice",
                "casting": store.preprod_dir(pid) / "voices"}[kind]  # fmt: skip
        work.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if any(j["production"] == pid and j["status"] in ACTIVE for j in self._jobs.values()):
                raise HTTPException(409, "a job for this production is already queued or running")
            jid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
            job = {
                "id": jid, "production": pid, "kind": kind, "status": "queued",
                "created": time.time(), "started": None, "ended": None, "pid": None, "returncode": None,
                "error": None, "plan": str(plan.relative_to(PROJECT)) if plan else None,
                "out": str(work.relative_to(PROJECT)),
                "log": f"productions/{pid}/jobs/{jid}.log", "summary": None, "character": character,
            }  # fmt: skip
            self._jobs[jid] = job
            self._save(job)
        return dict(job)

    def cancel(self, jid: str) -> dict:
        with self._lock:
            job = self._jobs.get(jid)
            if not job:
                raise HTTPException(404, "no such job")
            if job["status"] == "queued":
                job.update(status="cancelled", ended=time.time())
            elif job["status"] == "running":
                job["status"] = "cancelling"
                try:
                    os.killpg(os.getpgid(job["pid"]), signal.SIGTERM)
                except (ProcessLookupError, TypeError):
                    pass
            self._save(job)
            return dict(job)

    def log_tail(self, jid: str, lines: int = 200) -> list[str]:
        job = self.get(jid)
        f = PROJECT / job["log"]
        if not f.exists():
            return []
        text = f.read_text(errors="replace").replace("\r", "\n")
        return [ln for ln in text.splitlines() if ln.strip()][-lines:]

    # ------------------------------------------------------------ runner

    def start(self) -> None:
        threading.Thread(target=self._loop, name="job-runner", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # the runner must never die
                print(f"job runner error: {exc!r}", file=sys.stderr, flush=True)
            self._stop.wait(1.0)

    def _tick(self) -> None:
        with self._lock:
            running = [j for j in self._jobs.values() if j["status"] in ("running", "cancelling")]
            for job in running:
                self._check(job)
            if any(j["status"] in ("running", "cancelling") for j in self._jobs.values()):
                return
            queued = sorted((j for j in self._jobs.values() if j["status"] == "queued"), key=lambda j: j["created"])
            if queued:
                self._spawn(queued[0])

    def _spawn(self, job: dict) -> None:
        task = {
            "render": ["-m", "storyvid.pipeline", str(PROJECT / (job["plan"] or "")), "--out", str(PROJECT / job["out"])],
            "preprod": ["-m", "storyvid.agents", "preprod", job["production"]],
            "audition": ["-m", "storyvid.audition", job["production"]],
            "casting": ["-m", "storyvid.casting", "recast", job["production"], job.get("character") or ""],
        }[job["kind"]]
        # Keep the system awake for the job (on AC power this also blocks system sleep); the display may sleep.
        cmd = ["caffeinate", "-ims", sys.executable, *task]
        with open(PROJECT / job["log"], "a") as log:  # the child keeps its own copy of the descriptor
            proc = subprocess.Popen(cmd, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self._procs[job["id"]] = proc
        job.update(status="running", started=time.time(), pid=proc.pid)
        self._save(job)
        if job["kind"] == "render":
            store.set_step(job["production"], "render", "running")
        elif job["kind"] in ("audition", "casting"):
            store.set_step(job["production"], "voice", "running")

    def _check(self, job: dict) -> None:
        proc = self._procs.get(job["id"])
        if proc is not None:
            code = proc.poll()
            if code is None:
                return
        elif _alive(job["pid"]):
            return  # started by an earlier API process; still rendering
        else:
            code = None
        events = latest_run(PROJECT / job["out"])
        done_type = FINISHED[job.get("kind", "render")]
        finished = next((e for e in reversed(events) if e["type"] in (done_type, "run_failed")), None)
        if job["status"] == "cancelling":
            status = "cancelled"
        elif finished and finished["type"] == done_type and code in (0, None):
            status = "succeeded"
        else:
            status = "failed"
            job["error"] = (finished or {}).get("error") or (
                f"render process exited with code {code}" if code is not None else
                "render process ended while the studio was not running"
            )  # fmt: skip
        summary = store.progress(events) if job.get("kind", "render") == "render" else store.agent_progress(events)
        job.update(status=status, ended=time.time(), returncode=code, summary=summary)
        self._procs.pop(job["id"], None)
        self._save(job)
        if job.get("kind", "render") != "render":
            # Agents set their own stages as they work; a failure lands on whichever stage was running.
            if status != "succeeded":
                store.fail_running_steps(job["production"], "failed" if status == "failed" else "pending")
            return
        # A cancelled re-render leaves the previous film (and its results) untouched, so the stages
        # keep saying so; a failure is shown on the render stage either way.
        had_film = (PROJECT / job["out"] / "final.mp4").exists()
        steps = {"succeeded": ("done", "done", "done"), "failed": ("failed", None, None),
                 "cancelled": ("done" if had_film else "pending", None, None)}[status]  # fmt: skip
        for step, value in zip(("render", "assemble", "film"), steps):
            if value:
                store.set_step(job["production"], step, value)
