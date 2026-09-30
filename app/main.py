"""Qreate API + studio UI.

Run:  uvicorn app.main:app --reload
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .jobs import executor, store
from .models import BatchRequest, JobRequest, SceneEdit
from .pipeline import regenerate_scene, run_job
from .providers.research import trending_topics
from .providers import wan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Qreate", version="1.0", description="LLM-powered video pipeline for the Qoneqt Global Feed")


def _job_or_404(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, f"No job with id {job_id}")
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
    batch_id = "b-" + uuid.uuid4().hex[:6]
    ids = []
    for topic in [t.strip() for t in req.topics if t.strip()]:
        jr = JobRequest(topic=topic, **req.model_dump(exclude={"topics"}))
        job = store.create(jr, batch_id=batch_id)
        executor.submit(run_job, store, job["id"])
        ids.append(job["id"])
    if not ids:
        raise HTTPException(422, "Add at least one topic, one per line.")
    return {"batch_id": batch_id, "ids": ids}


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": store.list()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = _job_or_404(job_id)
    job["outputs"] = {k: f"/api/jobs/{job_id}/{k}" for k in job["outputs"]}
    return job


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


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    logging.getLogger("qreate").exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
