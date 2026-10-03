"""Job store + worker pool.

Jobs are persisted as JSON on disk (data/jobs/<id>/job.json) so they survive
restarts and can be inspected by hand. A thread pool runs pipelines in
parallel; swap it for Celery/Redis when you need multiple machines.
"""
from __future__ import annotations

import json
import shutil
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

TERMINAL = ("done", "needs_review", "failed")


def _fresh_stages() -> dict[str, dict]:
    return {k: {"label": label, "status": "pending", "detail": ""} for k, label in STAGES}


def progress_of(job: dict) -> dict:
    """How far along a job is, for progress bars and list rows."""
    stages = list(job.get("stages", {}).values())
    done = sum(1 for s in stages if s["status"] in ("done", "skipped"))
    running = next((s for s in stages if s["status"] == "running"), None)
    return {
        "done": done,
        "total": len(stages),
        "ratio": round(done / len(stages), 4) if stages else 0.0,
        "label": running["label"] if running else None,
        "detail": (running or {}).get("detail") or "",
    }


class JobStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        # Bumped on every write so SSE streams can detect change without diffing payloads.
        self.revision = 0
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
        self.revision += 1
        p = self.dir(job["id"]) / "job.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        # Windows refuses the swap while anything else holds the target open - a
        # virus scanner, the search indexer, or a reader mid-poll. Losing a whole
        # job to that is not acceptable, so retry briefly before giving up.
        for attempt in range(6):
            try:
                tmp.replace(p)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def create(self, req: JobRequest, batch_id: str | None = None) -> dict:
        job_id = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:5]
        job = {
            "id": job_id,
            "batch_id": batch_id,
            "request": req.model_dump(),
            "status": "queued",
            "created": time.time(),
            "updated": time.time(),
            "stages": _fresh_stages(),
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

    def delete(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.pop(job_id, None)
            if job is None:
                return False
            self.revision += 1
        shutil.rmtree(config.JOBS_DIR / job_id, ignore_errors=True)
        return True

    def reset(self, job_id: str) -> None:
        """Wipe stage and result state so a finished or failed job can run again."""
        with self.lock:
            job = self.jobs[job_id]
            # The rerun writes a new script, so old per-scene voice and visuals must not be reused.
            d = self.dir(job_id)
            for sub in ("scenes", "output"):
                shutil.rmtree(d / sub, ignore_errors=True)
            for name in ("notes.json", "plan.json", "scenes.txt", "joined.mp4", "package.zip"):
                (d / name).unlink(missing_ok=True)
            job.update(
                status="queued", stages=_fresh_stages(), plan=None, critique=None, qa=None,
                scene_assets=[], outputs={}, log=[], error=None, updated=time.time(),
            )
            self._save(job)

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
                    "updated": j.get("updated", j["created"]),
                    "language": j["request"].get("language"),
                    "community": j["request"].get("community"),
                    "scenes": len(((j.get("plan") or {}).get("scenes")) or []),
                    "duration": (j.get("qa") or {}).get("duration"),
                    "score": (j.get("critique") or {}).get("overall"),
                    "progress": progress_of(j),
                    "has_video": bool(j["outputs"].get("video")),
                }
                for j in jobs
            ]

    def stats(self) -> dict:
        """Headline numbers for the studio dashboard."""
        with self.lock:
            jobs = list(self.jobs.values())
        ready = [j for j in jobs if j["status"] in ("done", "needs_review")]
        scores = [(j.get("critique") or {}).get("overall") for j in ready]
        scores = [s for s in scores if s]
        runtimes = []
        for j in ready:
            # Sum the stage times rather than first start to last end, so a scene edit
            # made hours later doesn't count the idle gap as build time.
            secs = [s["ended"] - s["started"] for s in j["stages"].values()
                    if s.get("started") and s.get("ended") and s["ended"] >= s["started"]]
            if secs:
                runtimes.append(sum(secs))
        return {
            "total": len(jobs),
            "ready": len(ready),
            "running": sum(1 for j in jobs if j["status"] in ("queued", "running")),
            "failed": sum(1 for j in jobs if j["status"] == "failed"),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
            "avg_seconds": round(sum(runtimes) / len(runtimes), 1) if runtimes else None,
        }

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
            prev, st["status"] = st["status"], status
            if detail:
                st["detail"] = detail
            # Progress updates ("2/5 scenes") re-send "running"; only the first one starts the clock.
            if status == "running" and prev != "running":
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
