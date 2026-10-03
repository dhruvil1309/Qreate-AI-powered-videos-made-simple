"""Qreate API + studio UI.

Run:  uvicorn app.main:app --reload
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import AsyncIterator, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import config
from .jobs import TERMINAL, executor, progress_of, store
from .models import BatchRequest, HookPick, JobRequest, PlanEdit, SceneEdit, ScenePlan
from .pipeline import ensure_poster, regenerate_scene, run_job, write_package
from .providers.research import trending_topics
from .providers import wan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Qreate", version="1.0", description="LLM-powered video pipeline for the Qoneqt Global Feed")


def _job_or_404(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, f"No job with id {job_id}")
    return job


def _with_output_urls(job: dict) -> dict:
    """Swap absolute disk paths for the URLs the studio can actually fetch."""
    job["outputs"] = {k: f"/api/jobs/{job['id']}/{k}" for k in job["outputs"]}
    job["progress"] = progress_of(job)
    return job


@app.get("/api/health")
def health():
    wan_ready, wan_reason = wan.readiness()
    visuals = (["pexels"] if config.PEXELS_API_KEY else []) + (["pollinations"] if config.USE_POLLINATIONS else []) + ["generated-cards"]
    if wan_ready:
        visuals.insert(0, "wan2.1")
    return {
        "ok": True,
        "offline_mode": config.OFFLINE_MODE,
        "llm_providers": config.llm_providers_available(),
        "research": ["wikipedia"] + (["tavily"] if config.TAVILY_API_KEY else []),
        "visuals": visuals,
        "voice": ([f"sarvam ({config.SARVAM_TTS_MODEL}, {config.SARVAM_TTS_SPEAKER})"] if config.TTS_PROVIDER == "sarvam" and config.SARVAM_API_KEY else [])
        + (["edge-tts"] if config.USE_EDGE_TTS else []) + (["espeak-ng"] if shutil.which("espeak-ng") else []) + ["silent"],
        "critic": "llm" if config.CRITIC_USE_LLM else "heuristic",
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "workers": config.MAX_WORKERS,
        "wan2_1": {"enabled": config.WAN_ENABLED, "ready": wan_ready, "detail": wan_reason},
    }


@app.get("/api/trends")
def trends(geo: str = "IN"):
    return {"topics": trending_topics(geo)}


@app.post("/api/jobs", status_code=202)
def create_job(req: JobRequest):
    job = store.create(req)
    executor.submit(run_job, store, job["id"])
    return {"id": job["id"], "status": job["status"]}


@app.post("/api/batch", status_code=202)
def create_batch(req: BatchRequest):
    topics = [t.strip() for t in req.topics if t.strip()]
    if not topics:
        raise HTTPException(422, "Add at least one topic, one per line.")
    # Validate every topic before queueing any, so one bad line doesn't leave half a batch.
    opts = req.model_dump(exclude={"topics"})
    reqs = []
    for n, topic in enumerate(topics, 1):
        try:
            reqs.append(JobRequest(topic=topic, **opts))
        except ValidationError as e:
            raise HTTPException(422, f"Topic {n} ({topic[:40]!r}): {e.errors()[0]['msg']}") from e
    batch_id = "b-" + uuid.uuid4().hex[:6]
    ids = []
    for jr in reqs:
        job = store.create(jr, batch_id=batch_id)
        executor.submit(run_job, store, job["id"])
        ids.append(job["id"])
    return {"batch_id": batch_id, "ids": ids}


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": store.list(), "stats": store.stats()}


@app.get("/api/stats")
def stats():
    return store.stats()


# ------------------------------------------------------------------ live streams
async def _sse(request: Request, snapshot: Callable[[], object], done: Callable[[object], bool]) -> StreamingResponse:
    """Push `snapshot()` to the browser whenever the job store changes.

    The studio keeps one of these open instead of polling, so progress appears
    the moment a stage flips. Heartbeat comments keep proxies from closing it.
    """

    async def events() -> AsyncIterator[str]:
        last_rev, last_beat = -1, 0.0
        while True:
            if await request.is_disconnected():
                return
            if store.revision != last_rev:
                last_rev = store.revision
                payload = snapshot()
                if payload is None:
                    yield "event: gone\ndata: {}\n\n"
                    return
                yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                if done(payload):
                    # Tell the client to close: EventSource would otherwise reconnect forever.
                    yield "event: end\ndata: {}\n\n"
                    return
            if time.monotonic() - last_beat > 15:
                last_beat = time.monotonic()
                yield ": keepalive\n\n"
            await asyncio.sleep(0.35)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/api/stream/jobs")
async def stream_jobs(request: Request):
    return await _sse(request, lambda: {"jobs": store.list(), "stats": store.stats()}, lambda _: False)


@app.get("/api/stream/jobs/{job_id}")
async def stream_job(request: Request, job_id: str):
    _job_or_404(job_id)

    def snapshot():
        job = store.get(job_id)
        return _with_output_urls(job) if job else None

    # Stop streaming once the job can no longer change on its own.
    return await _sse(request, snapshot, lambda j: j["status"] in TERMINAL)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return _with_output_urls(_job_or_404(job_id))


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = _job_or_404(job_id)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "This video is still being made. Wait for it to finish before deleting it.")
    store.delete(job_id)
    return {"id": job_id, "deleted": True}


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str):
    job = _job_or_404(job_id)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "This video is already being made.")
    store.reset(job_id)
    executor.submit(run_job, store, job_id)
    return {"id": job_id, "status": "queued"}


def _plan_or_409(job: dict) -> ScenePlan:
    if not job.get("plan"):
        raise HTTPException(409, "This job has no scene plan yet.")
    return ScenePlan.model_validate(job["plan"])


@app.patch("/api/jobs/{job_id}/plan")
def edit_plan(job_id: str, edit: PlanEdit):
    """Edit the post copy. Nothing is re-rendered: only the package is rewritten."""
    job = _job_or_404(job_id)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "This video is still being made. Wait for it to finish, then edit the post.")
    plan = _plan_or_409(job)
    fields = edit.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(422, "Nothing to change.")
    plan = plan.model_copy(update=fields)
    plan = ScenePlan.model_validate(plan.model_dump())  # re-run hashtag normalisation
    store.update(job_id, plan=plan.model_dump())
    if job["outputs"].get("package"):
        write_package(store.dir(job_id), plan)
    store.log(job_id, f"Post copy edited ({', '.join(fields)})")
    return {"id": job_id, "plan": plan.model_dump()}


@app.post("/api/jobs/{job_id}/hook", status_code=202)
def pick_hook(job_id: str, pick: HookPick):
    """Swap the opening line, then re-render only the first scene."""
    job = _job_or_404(job_id)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "This video is still being made. Wait for it to finish, then change the hook.")
    plan = _plan_or_409(job)
    text = (pick.text or "").strip()
    if not text:
        if pick.index is None:
            raise HTTPException(422, "Send a hook index or some text.")
        if pick.index >= len(plan.hook_options):
            raise HTTPException(422, f"Only {len(plan.hook_options)} hook options exist.")
        text = plan.hook_options[pick.index].strip()
    if text == plan.scenes[0].voiceover.strip():
        raise HTTPException(409, "That is already the opening line.")
    store.update(job_id, status="running")
    executor.submit(regenerate_scene, store, job_id, 0, SceneEdit(voiceover=text))
    return {"id": job_id, "status": "running", "hook": text}


@app.post("/api/jobs/{job_id}/scenes/{scene_no}/regenerate", status_code=202)
def regen(job_id: str, scene_no: int, edit: SceneEdit):
    job = _job_or_404(job_id)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "This video is still being made. Wait for it to finish, then edit a scene.")
    if not job.get("plan"):
        raise HTTPException(409, "This job has no scene plan yet.")
    n = len(job["plan"]["scenes"])
    if not 1 <= scene_no <= n:
        raise HTTPException(422, f"Scene must be between 1 and {n}.")
    store.update(job_id, status="running")  # so clients polling right away see the change
    executor.submit(regenerate_scene, store, job_id, scene_no - 1, edit)
    return {"id": job_id, "status": "running"}


def _file(job_id: str, key: str, media: str, download: bool = False):
    job = _job_or_404(job_id)
    path = job["outputs"].get(key)
    if not path or not Path(path).exists():
        raise HTTPException(404, f"The {key} isn't ready yet.")
    name = Path(path).name
    return FileResponse(path, media_type=media, filename=name if download else None)


@app.get("/api/jobs/{job_id}/video")
def video(job_id: str, download: bool = False):
    return _file(job_id, "video", "video/mp4", download)


@app.get("/api/jobs/{job_id}/thumbnail")
def thumb(job_id: str):
    return _file(job_id, "thumbnail", "image/jpeg")


@app.get("/api/jobs/{job_id}/package")
def package(job_id: str):
    return _file(job_id, "package", "application/zip", download=True)


def _scene_dir_or_404(job_id: str, scene_no: int) -> Path:
    job = _job_or_404(job_id)
    n = len((job.get("plan") or {}).get("scenes") or [])
    if not 1 <= scene_no <= max(n, 1):
        raise HTTPException(404, f"Scene {scene_no} does not exist.")
    return config.JOBS_DIR / job_id / "scenes" / f"{scene_no - 1:02d}"


def _scene_file(job_id: str, scene_no: int, name: str, media: str):
    path = _scene_dir_or_404(job_id, scene_no) / name
    if not path.exists():
        raise HTTPException(404, f"Scene {scene_no} has no {name} yet.")
    return FileResponse(path, media_type=media)


@app.get("/api/jobs/{job_id}/scenes/{scene_no}/poster")
def scene_poster(job_id: str, scene_no: int):
    # Built lazily, so scenes rendered before posters existed still have one.
    poster = ensure_poster(_scene_dir_or_404(job_id, scene_no))
    if not poster:
        raise HTTPException(404, f"Scene {scene_no} has not been rendered yet.")
    return FileResponse(poster, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/scenes/{scene_no}/clip")
def scene_clip(job_id: str, scene_no: int):
    return _scene_file(job_id, scene_no, "scene.mp4", "video/mp4")


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    logging.getLogger("qreate").exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
