"""Job store + worker pool.

Jobs are persisted as JSON on disk (data/jobs/<id>/job.json) so they survive
restarts and can be inspected by hand. A thread pool runs pipelines in
parallel; swap it for Celery/Redis when you need multiple machines.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .models import JobRequest

STAGES = [
    ("research", "Research the topic"),
    ("script", "Write hook and scene plan"),
    ("critic", "Critique and rewrite"),
    ("assets", "Find visuals, record voice"),
    ("render", "Render scenes with captions"),
    ("assemble", "Edit, mix and level audio"),
    ("qa", "Run quality checks"),
    ("package", "Package for Qoneqt"),
]


class JobStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        for f in config.JOBS_DIR.glob("*/job.json"):
            try:
                try:
                    contents = f.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    contents = f.read_text(encoding="cp1252")
                job = json.loads(contents)
            except json.JSONDecodeError:
                continue
            if job.get("status") in ("queued", "running"):
                job["status"] = "failed"
                job["error"] = "Interrupted by a server restart. Create the video again."
            self.jobs[job["id"]] = job

    def dir(self, job_id: str) -> Path:
        d = config.JOBS_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save(self, job: dict) -> None:
        p = self.dir(job["id"]) / "job.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)

    def create(self, req: JobRequest, batch_id: str | None = None) -> dict:
        job_id = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:5]
        job = {
            "id": job_id,
            "batch_id": batch_id,
            "request": req.model_dump(),
            "status": "queued",
            "created": time.time(),
            "updated": time.time(),
            "stages": {k: {"label": label, "status": "pending", "detail": ""} for k, label in STAGES},
            "plan": None,
            "critique": None,
            "qa": None,
            "scene_assets": [],
            "outputs": {},
            "log": [],
            "error": None,
        }
        with self.lock:
            self.jobs[job_id] = job
            self._save(job)
        return job

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            j = self.jobs.get(job_id)
            return json.loads(json.dumps(j)) if j else None

    def list(self, limit: int = 50) -> list[dict]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)[:limit]
            return [
                {
                    "id": j["id"],
                    "batch_id": j.get("batch_id"),
                    "topic": j["request"]["topic"],
                    "status": j["status"],
                    "title": (j.get("plan") or {}).get("title"),
                    "created": j["created"],
                    "has_video": bool(j["outputs"].get("video")),
                }
                for j in jobs
            ]

    def update(self, job_id: str, **fields) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.update(fields)
            job["updated"] = time.time()
            self._save(job)

    def stage(self, job_id: str, name: str, status: str, detail: str = "") -> None:
        with self.lock:
            job = self.jobs[job_id]
            st = job["stages"][name]
            st["status"] = status
            if detail:
                st["detail"] = detail
            if status == "running":
                st["started"] = time.time()
            elif status in ("done", "failed", "skipped"):
                st["ended"] = time.time()
            job["updated"] = time.time()
            self._save(job)

    def log(self, job_id: str, msg: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")
            job["log"] = job["log"][-200:]
            self._save(job)


store = JobStore()
executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS, thread_name_prefix="qreate")
