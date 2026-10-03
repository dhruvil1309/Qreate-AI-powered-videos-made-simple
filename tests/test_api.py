"""API-surface tests for the studio endpoints.

Run with:  OFFLINE_MODE=1 pytest -q

These never start the pipeline: jobs are seeded straight into the store so the
tests stay fast and deterministic. test_pipeline.py covers a real render.
"""
import json
import os

os.environ.setdefault("OFFLINE_MODE", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.jobs import STAGES, store  # noqa: E402
from app.main import app  # noqa: E402
from app.models import JobRequest  # noqa: E402

client = TestClient(app)

PLAN = {
    "title": "Why ISRO does space on a budget",
    "hook": "India reached Mars for less than a movie.",
    "hook_options": ["India reached Mars for less than a movie.", "Mars on a shoestring"],
    "scenes": [
        {"id": 1, "voiceover": "India reached Mars for less than a movie.", "caption": "Mars on a budget",
         "visual": {"mode": "stock", "query": "rocket launch", "prompt": ""}},
        {"id": 2, "voiceover": "Reuse proven parts and test smart.", "caption": "Reuse, test smart",
         "visual": {"mode": "stock", "query": "engineers", "prompt": ""}},
    ],
    "cta": "Follow for more", "description": "How ISRO keeps missions affordable.",
    "hashtags": ["#ISRO", "#space"], "sources": [], "generated_by": "test",
}


@pytest.fixture
def job():
    """A finished-looking job, removed again once the test is done."""
    j = store.create(JobRequest(topic="Why ISRO missions cost so little", community="Space Nerds"))
    store.update(j["id"], status="done", plan=PLAN)
    yield store.get(j["id"])
    store.delete(j["id"])


def test_health_and_stats_shape():
    h = client.get("/api/health").json()
    assert h["ok"] and isinstance(h["visuals"], list) and "workers" in h
    s = client.get("/api/stats").json()
    assert {"total", "ready", "running", "failed"} <= s.keys()


def test_list_carries_progress_and_stats(job):
    body = client.get("/api/jobs").json()
    row = next(r for r in body["jobs"] if r["id"] == job["id"])
    assert row["progress"]["total"] == len(STAGES)
    assert row["scenes"] == 2 and row["title"] == PLAN["title"]
    assert body["stats"]["total"] >= 1


def test_progress_updates_keep_the_stage_start_time(job, monkeypatch):
    clock = iter(range(1_000, 2_000))
    monkeypatch.setattr("app.jobs.time.time", lambda: next(clock))
    store.stage(job["id"], "assets", "running", "0/5 scenes")
    started = store.get(job["id"])["stages"]["assets"]["started"]
    store.stage(job["id"], "assets", "running", "3/5 scenes")
    assert store.get(job["id"])["stages"]["assets"]["started"] == started
    store.stage(job["id"], "assets", "done")
    store.stage(job["id"], "assets", "running")  # an edit re-runs the stage: a new clock
    assert store.get(job["id"])["stages"]["assets"]["started"] > started


def test_get_job_returns_urls_not_disk_paths(job):
    store.update(job["id"], outputs={"video": "/some/disk/path.mp4"})
    body = client.get(f"/api/jobs/{job['id']}").json()
    assert body["outputs"]["video"] == f"/api/jobs/{job['id']}/video"
    assert body["progress"]["ratio"] == 0.0


def test_unknown_job_is_404():
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.delete("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/retry").status_code == 404


def test_patch_plan_normalises_hashtags_and_keeps_other_fields(job):
    r = client.patch(f"/api/jobs/{job['id']}/plan",
                     json={"description": "New copy.", "hashtags": ["ISRO", "#ISRO", "deep space"]})
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert plan["description"] == "New copy."
    assert plan["hashtags"] == ["#ISRO", "#deepspace"]  # deduped, hashed, spaces stripped
    assert plan["title"] == PLAN["title"]  # untouched fields survive
    assert plan["scenes"][0]["caption"] == "Mars on a budget"


def test_patch_plan_rejects_an_empty_edit(job):
    assert client.patch(f"/api/jobs/{job['id']}/plan", json={}).status_code == 422


def test_patch_plan_rewrites_the_package(job, tmp_path):
    d = store.dir(job["id"])
    (d / "output").mkdir(exist_ok=True)
    store.update(job["id"], outputs={"package": str(d / "package.zip")})
    client.patch(f"/api/jobs/{job['id']}/plan", json={"description": "Repackaged."})
    assert "Repackaged." in (d / "output" / "post.txt").read_text(encoding="utf-8")
    assert (d / "package.zip").exists()
    assert json.loads((d / "output" / "plan.json").read_text(encoding="utf-8"))["description"] == "Repackaged."


def test_hook_pick_validates_its_input(job):
    assert client.post(f"/api/jobs/{job['id']}/hook", json={}).status_code == 422
    assert client.post(f"/api/jobs/{job['id']}/hook", json={"index": 9}).status_code == 422
    # Option 0 is already the opening line, so there is nothing to re-render.
    assert client.post(f"/api/jobs/{job['id']}/hook", json={"index": 0}).status_code == 409


def test_busy_jobs_refuse_edits_and_deletion(job):
    store.update(job["id"], status="running")
    jid = job["id"]
    assert client.delete(f"/api/jobs/{jid}").status_code == 409
    assert client.post(f"/api/jobs/{jid}/retry").status_code == 409
    assert client.patch(f"/api/jobs/{jid}/plan", json={"title": "x"}).status_code == 409
    assert client.post(f"/api/jobs/{jid}/hook", json={"text": "Something else"}).status_code == 409
    assert client.post(f"/api/jobs/{jid}/scenes/1/regenerate", json={}).status_code == 409
    store.update(jid, status="done")  # let the fixture clean up


def test_delete_removes_the_job_and_its_folder():
    j = store.create(JobRequest(topic="Delete me from the studio"))
    store.update(j["id"], status="failed")  # a queued job is protected from deletion
    d = store.dir(j["id"])
    assert d.exists()
    assert client.delete(f"/api/jobs/{j['id']}").status_code == 200
    assert client.get(f"/api/jobs/{j['id']}").status_code == 404
    assert not d.exists()


def test_scene_media_404s_before_a_render(job):
    assert client.get(f"/api/jobs/{job['id']}/scenes/1/poster").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/scenes/1/clip").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/scenes/7/clip").status_code == 404


def test_job_stream_sends_a_snapshot_then_ends(job):
    """A terminal job streams one frame and closes, so EventSource stops retrying."""
    with client.stream("GET", f"/api/stream/jobs/{job['id']}") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        chunks = []
        for line in r.iter_lines():
            chunks.append(line)
            if line.startswith("event: end"):
                break
    payload = next(json.loads(c[5:]) for c in chunks if c.startswith("data:") and len(c) > 6)
    assert payload["id"] == job["id"] and payload["status"] == "done"


def test_batch_rejects_blank_topics():
    assert client.post("/api/batch", json={"topics": ["  ", ""]}).status_code == 422


def test_batch_validates_every_topic_before_queueing_any():
    before = len(store.jobs)
    r = client.post("/api/batch", json={"topics": ["How UPI changed payments in India", "ab"]})
    assert r.status_code == 422 and "Topic 2" in r.json()["detail"]
    assert len(store.jobs) == before


def test_retry_reset_discards_the_old_scene_media(job):
    old = store.dir(job["id"]) / "scenes" / "00" / "assets.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}", encoding="utf-8")
    store.reset(job["id"])
    assert not old.exists() and store.get(job["id"])["plan"] is None
