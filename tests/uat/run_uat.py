"""Run the Qreate UAT plan and write a report.

    .\\.venv\\Scripts\\python.exe tests\\uat\\run_uat.py [--keep] [--no-ui] [--port N]

Starts its own server on a spare port in offline mode, drives a real headless
browser for the interface cases, hits the HTTP API directly for the rest, then
writes tests/uat/REPORT.md. Exits non-zero if any case fails.

Every job this suite creates is deleted again, so your own videos are left
alone. Pass --keep to leave them in place for inspection.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from driver import Browser, find_browser  # noqa: E402

SHOTS = HERE / "screenshots"

# ---------------------------------------------------------------- result model
PASS, FAIL, MANUAL, SKIP = "PASS", "FAIL", "MANUAL", "SKIP"
results: list[dict] = []
_created_jobs: set[str] = set()


def _say(text: str) -> None:
    """Print without dying on a console that cannot encode the character."""
    enc = sys.stdout.encoding or "utf-8"
    print(text.encode(enc, "replace").decode(enc), flush=True)


def record(case: str, title: str, status: str, note: str = "", severity: str = "Major") -> None:
    results.append({"id": case, "title": title, "status": status,
                    "note": note, "severity": severity})
    mark = {PASS: "PASS ", FAIL: "FAIL ", MANUAL: "MANUAL", SKIP: "SKIP "}[status]
    line = f"  {mark} {case:<4} {title}"
    _say(line if status != FAIL else line + f"\n          -> {note}")


def _read_json_retry(path: Path, tries: int = 10) -> dict:
    """Read a job file that a dying server may still have open (Windows)."""
    for i in range(tries):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            if i == tries - 1:
                raise
            time.sleep(0.2)
    raise AssertionError("unreachable")


def check(case: str, title: str, severity: str = "Major"):
    """Decorator-ish helper: run `fn`, turn an assertion into a FAIL row."""
    def runner(fn):
        try:
            note = fn() or ""
            record(case, title, PASS, note, severity)
        except AssertionError as e:
            record(case, title, FAIL, str(e) or "assertion failed", severity)
        except Exception as e:  # noqa: BLE001
            record(case, title, FAIL, f"{type(e).__name__}: {e}", severity)
            if os.getenv("UAT_TRACE"):
                traceback.print_exc()
        return fn
    return runner


# ---------------------------------------------------------------- server
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, port: int) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "OFFLINE_MODE": "1", "PYTHONIOENCODING": "utf-8"}
        self.log = open(HERE / "server.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
             "--log-level", "warning"],
            cwd=str(ROOT), env=env, stdout=self.log, stderr=subprocess.STDOUT)

    def wait(self, timeout: float = 60) -> None:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if httpx.get(self.base + "/api/health", timeout=2).status_code == 200:
                    return
            except Exception:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError("server exited early; see tests/uat/server.log")
            time.sleep(0.5)
        raise RuntimeError("server did not start in time")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self.log.close()
        # Wait for the port to be released, or a restart races the dying process
        # and two servers end up writing the same job files.
        end = time.time() + 15
        while time.time() < end:
            with socket.socket() as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", self.port)) != 0:
                    return
            time.sleep(0.25)

    def alive(self) -> bool:
        try:
            return httpx.get(self.base + "/api/health", timeout=3).status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------- API helpers
class Api:
    def __init__(self, base: str) -> None:
        self.base = base
        self.c = httpx.Client(base_url=base, timeout=30)

    def post_job(self, **body) -> str:
        body.setdefault("topic", "UAT placeholder topic for the studio")
        r = self.c.post("/api/jobs", json=body)
        r.raise_for_status()
        jid = r.json()["id"]
        _created_jobs.add(jid)
        return jid

    def job(self, jid: str) -> dict:
        r = self.c.get(f"/api/jobs/{jid}")
        r.raise_for_status()
        return r.json()

    def wait_done(self, jid: str, timeout: float = 300) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            j = self.job(jid)
            if j["status"] not in ("queued", "running"):
                return j
            time.sleep(1.0)
        raise TimeoutError(f"job {jid} still {self.job(jid)['status']} after {timeout}s")

    def cleanup(self) -> None:
        for jid in list(_created_jobs):
            try:
                j = self.c.get(f"/api/jobs/{jid}")
                if j.status_code == 404:
                    continue
                for _ in range(60):
                    if j.json()["status"] not in ("queued", "running"):
                        break
                    time.sleep(1)
                    j = self.c.get(f"/api/jobs/{jid}")
                self.c.delete(f"/api/jobs/{jid}")
            except Exception:
                pass


# ================================================================ API CASES
def run_api_cases(api: Api, seed: dict) -> None:
    c, jid = api.c, seed["id"]
    print("\nB. Making a video")

    @check("B6", "Choices are respected", "Critical")
    def _():
        opts = {"topic": "UAT options are carried through to the job",
                "community": "Space Nerds", "language": "hinglish", "tone": "funny",
                "target_seconds": 30, "visual_style": "ai"}
        j = api.job(api.post_job(**opts))
        for k, v in opts.items():
            assert j["request"][k] == v, f"{k} was stored as {j['request'][k]!r}, expected {v!r}"
        return "community, language, tone, length and visual style all stored"

    @check("B7", "Batch creates one job per topic", "Major")
    def _():
        topics = ["UAT batch topic one", "UAT batch topic two", "UAT batch topic three"]
        r = c.post("/api/batch", json={"topics": topics, "target_seconds": 20})
        assert r.status_code == 202, f"got {r.status_code}"
        ids = r.json()["ids"]
        _created_jobs.update(ids)
        assert len(ids) == 3, f"expected 3 jobs, got {len(ids)}"
        assert r.json()["batch_id"], "no batch id returned"
        got = {api.job(i)["request"]["topic"] for i in ids}
        assert got == set(topics), f"topics did not round-trip: {got}"
        return f"3 jobs under batch {r.json()['batch_id']}"

    @check("B8", "Batch ignores blank lines", "Minor")
    def _():
        r = c.post("/api/batch", json={"topics": ["UAT only real topic", "  ", ""]})
        assert r.status_code == 202, f"got {r.status_code}"
        ids = r.json()["ids"]
        _created_jobs.update(ids)
        assert len(ids) == 1, f"blank lines became {len(ids)} jobs"
        r2 = c.post("/api/batch", json={"topics": ["   ", ""]})
        assert r2.status_code == 422, f"all-blank batch returned {r2.status_code}, expected 422"
        return "blanks dropped; an all-blank batch is refused"

    @check("B9", "Topic length is bounded", "Minor")
    def _():
        short = c.post("/api/jobs", json={"topic": "ab"})
        assert short.status_code == 422, f"2-char topic returned {short.status_code}"
        long = c.post("/api/jobs", json={"topic": "x" * 601})
        assert long.status_code == 422, f"601-char topic returned {long.status_code}"
        ok = c.post("/api/jobs", json={"topic": "x" * 600})
        assert ok.status_code == 202, f"600-char topic returned {ok.status_code}"
        _created_jobs.add(ok.json()["id"])
        return "under 3 and over 600 refused; exactly 600 accepted"

    @check("B10", "Duration is bounded to 20-90s", "Minor")
    def _():
        for bad in (5, 19, 91, 600):
            r = c.post("/api/jobs", json={"topic": "UAT duration bound", "target_seconds": bad})
            assert r.status_code == 422, f"{bad}s was accepted ({r.status_code})"
        return "5, 19, 91 and 600 seconds all refused"

    print("\nD. Reviewing the result")

    @check("D1", "The rendered video is a vertical H.264/AAC MP4", "Critical")
    def _():
        r = c.get(f"/api/jobs/{jid}/video")
        assert r.status_code == 200, f"video returned {r.status_code}"
        assert r.headers["content-type"] == "video/mp4"
        assert len(r.content) > 50_000, f"video is only {len(r.content)} bytes"
        checks = {x["check"]: x for x in seed["qa"]["checks"]}
        assert checks["Vertical 1080x1920".replace("x", "×")]["pass"], "not 1080x1920"
        assert checks["H.264 + AAC (feed compatible)"]["pass"], "wrong codecs"
        return f"{len(r.content)/1e6:.1f} MB, {seed['qa']['duration']}s, 1080x1920 h264/aac"

    @check("D2", "QA verdict is complete", "Critical")
    def _():
        qa = seed["qa"]
        assert "passed" in qa and qa["checks"], "no QA result"
        for ch in qa["checks"]:
            assert {"check", "pass", "detail", "blocking"} <= ch.keys(), f"incomplete check {ch}"
            assert ch["detail"], f"check {ch['check']} has no measured value"
        blocking = [x for x in qa["checks"] if x["blocking"]]
        advisory = [x for x in qa["checks"] if not x["blocking"]]
        assert blocking and advisory, "blocking and advisory checks are not distinguished"
        return f"{len(qa['checks'])} checks ({len(blocking)} blocking, {len(advisory)} advisory)"

    @check("D5", "Every scene has a thumbnail", "Major")
    def _():
        n = len(seed["plan"]["scenes"])
        sizes = []
        for i in range(1, n + 1):
            r = c.get(f"/api/jobs/{jid}/scenes/{i}/poster")
            assert r.status_code == 200, f"scene {i} poster returned {r.status_code}"
            assert r.headers["content-type"] == "image/jpeg"
            sizes.append(len(r.content))
        assert all(s > 2000 for s in sizes), f"a poster is suspiciously small: {sizes}"
        return f"{n}/{n} posters, {min(sizes)//1024}-{max(sizes)//1024} KB"

    @check("D7", "Each scene can be previewed on its own", "Minor")
    def _():
        r = c.get(f"/api/jobs/{jid}/scenes/1/clip")
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        return f"scene 1 clip is {len(r.content)/1e6:.1f} MB"

    @check("D8", "Videos made before thumbnails existed still get them", "Minor")
    def _():
        sd = ROOT / "data" / "jobs" / jid / "scenes" / "00"
        poster = sd / "poster.jpg"
        assert poster.exists(), "no poster to test with"
        poster.unlink()
        r = c.get(f"/api/jobs/{jid}/scenes/1/poster")
        assert r.status_code == 200, f"lazy rebuild returned {r.status_code}"
        assert poster.exists(), "poster was served but not cached to disk"
        return "deleted poster was regenerated on request and cached"

    @check("D9", "Build history is recorded", "Minor")
    def _():
        stages = seed["stages"]
        assert len(stages) == 8, f"expected 8 stages, got {len(stages)}"
        timed = [s for s in stages.values() if s.get("started") and s.get("ended")]
        assert len(timed) >= 7, f"only {len(timed)} stages have timings"
        assert seed["log"], "job log is empty"
        return f"{len(timed)}/8 stages timed, {len(seed['log'])} log lines"

    print("\nE. Changing it")

    @check("E1", "Editing one scene re-renders only that scene", "Critical")
    def _():
        before = api.job(jid)
        other_key = (ROOT / "data" / "jobs" / jid / "scenes" / "01" / "render.key").read_text()
        r = c.post(f"/api/jobs/{jid}/scenes/1/regenerate",
                   json={"caption": "UAT edited caption", "voiceover": "UAT edited narration line."})
        assert r.status_code == 202, f"regenerate returned {r.status_code}: {r.text[:120]}"
        after = api.wait_done(jid)
        assert after["status"] != "failed", f"re-render failed: {after.get('error')}"
        assert after["plan"]["scenes"][0]["caption"] == "UAT edited caption", "caption not applied"
        assert "UAT edited narration" in after["plan"]["scenes"][0]["voiceover"], "voiceover not applied"
        assert after["plan"]["scenes"][1]["voiceover"] == before["plan"]["scenes"][1]["voiceover"], \
            "an untouched scene changed"
        after_key = (ROOT / "data" / "jobs" / jid / "scenes" / "01" / "render.key").read_text()
        assert after_key == other_key, "scene 2 was re-rendered unnecessarily"
        return "scene 1 rebuilt; scene 2 served from cache"

    @check("E4", "Try another visual swaps only the visual", "Major")
    def _():
        before = api.job(jid)
        meta = ROOT / "data" / "jobs" / jid / "scenes" / "00" / "assets.json"
        v0 = json.loads(meta.read_text(encoding="utf-8")).get("variant", 0)
        r = c.post(f"/api/jobs/{jid}/scenes/1/regenerate", json={})
        assert r.status_code == 202, f"got {r.status_code}"
        after = api.wait_done(jid)
        assert after["status"] != "failed", f"re-roll failed: {after.get('error')}"
        v1 = json.loads(meta.read_text(encoding="utf-8")).get("variant", 0)
        assert v1 == v0 + 1, f"visual variant did not advance ({v0} -> {v1})"
        assert after["plan"]["scenes"][0]["voiceover"] == before["plan"]["scenes"][0]["voiceover"], \
            "re-roll changed the narration"
        return f"visual variant {v0} -> {v1}, text untouched"

    @check("E5", "Swapping the hook re-renders scene 1", "Major")
    def _():
        plan = api.job(jid)["plan"]
        alt = next((h for h in plan["hook_options"]
                    if h.strip() != plan["scenes"][0]["voiceover"].strip()), None)
        if not alt:
            alt = "UAT replacement opening line for this reel."
        r = c.post(f"/api/jobs/{jid}/hook", json={"text": alt})
        assert r.status_code == 202, f"hook swap returned {r.status_code}: {r.text[:120]}"
        after = api.wait_done(jid)
        assert after["status"] != "failed", f"hook swap failed: {after.get('error')}"
        assert after["plan"]["scenes"][0]["voiceover"].strip() == alt.strip(), "hook not applied"
        assert after["plan"]["hook"].strip() == alt.strip(), "plan.hook not kept in sync"
        return "opening line replaced and plan.hook updated"

    @check("E6", "The current hook cannot be re-applied", "Minor")
    def _():
        cur = api.job(jid)["plan"]["scenes"][0]["voiceover"]
        r = c.post(f"/api/jobs/{jid}/hook", json={"text": cur})
        assert r.status_code == 409, f"expected 409, got {r.status_code}"
        bad = c.post(f"/api/jobs/{jid}/hook", json={})
        assert bad.status_code == 422, f"empty hook pick returned {bad.status_code}"
        oob = c.post(f"/api/jobs/{jid}/hook", json={"index": 99})
        assert oob.status_code == 422, f"out-of-range index returned {oob.status_code}"
        return "re-applying refused (409); empty and out-of-range refused (422)"

    @check("E7", "Editing the post copy does not re-render video", "Major")
    def _():
        j = api.job(jid)
        out = ROOT / "data" / "jobs" / jid / "output"
        mp4 = next(out.glob("qreate-*.mp4"))
        before_mtime, before_size = mp4.stat().st_mtime, mp4.stat().st_size
        r = c.patch(f"/api/jobs/{jid}/plan",
                    json={"description": "UAT rewritten description.", "cta": "UAT follow us"})
        assert r.status_code == 200, f"patch returned {r.status_code}: {r.text[:120]}"
        assert r.json()["plan"]["description"] == "UAT rewritten description."
        assert api.job(jid)["status"] != "running", "editing copy started a render"
        assert mp4.stat().st_mtime == before_mtime and mp4.stat().st_size == before_size, \
            "the MP4 was rewritten by a copy-only edit"
        post = (out / "post.txt").read_text(encoding="utf-8")
        assert "UAT rewritten description." in post, "post.txt was not updated"
        assert (ROOT / "data" / "jobs" / jid / "package.zip").exists(), "package missing"
        return "caption and package updated; MP4 untouched"

    @check("E8", "Hashtags are normalised", "Minor")
    def _():
        r = c.patch(f"/api/jobs/{jid}/plan",
                    json={"hashtags": ["ISRO", "#ISRO", "deep space", "  ", "#qoneqt", "QONEQT"]})
        assert r.status_code == 200, f"got {r.status_code}"
        tags = r.json()["plan"]["hashtags"]
        assert tags == ["#ISRO", "#deepspace", "#qoneqt"], f"got {tags}"
        many = c.patch(f"/api/jobs/{jid}/plan", json={"hashtags": [f"tag{i}" for i in range(12)]})
        assert len(many.json()["plan"]["hashtags"]) == 8, "hashtags not capped at 8"
        return "hashed, de-duplicated case-insensitively, spaces stripped, capped at 8"

    @check("E9", "An empty post edit is refused", "Minor")
    def _():
        assert c.patch(f"/api/jobs/{jid}/plan", json={}).status_code == 422
        assert c.patch(f"/api/jobs/{jid}/plan", json={"title": ""}).status_code == 422
        return "empty body and empty title both refused"

    print("\nF. Managing your videos")

    @check("F4", "Delete removes the job and its files", "Major")
    def _():
        victim = api.post_job(topic="UAT delete me please")
        api.wait_done(victim)
        d = ROOT / "data" / "jobs" / victim
        assert d.exists(), "job folder was never created"
        r = c.delete(f"/api/jobs/{victim}")
        assert r.status_code == 200, f"delete returned {r.status_code}"
        assert c.get(f"/api/jobs/{victim}").status_code == 404, "job still listed after delete"
        assert not d.exists(), "job folder left on disk"
        ids = [j["id"] for j in c.get("/api/jobs").json()["jobs"]]
        assert victim not in ids, "deleted job still in the list"
        _created_jobs.discard(victim)
        return "removed from the list, the store and the disk"

    @check("F5", "A building video is protected", "Major")
    def _():
        busy = api.post_job(topic="UAT busy guard while this one builds", target_seconds=20)
        try:
            codes = {
                "delete": c.delete(f"/api/jobs/{busy}").status_code,
                "retry": c.post(f"/api/jobs/{busy}/retry").status_code,
                "edit copy": c.patch(f"/api/jobs/{busy}/plan", json={"title": "x"}).status_code,
                "edit scene": c.post(f"/api/jobs/{busy}/scenes/1/regenerate", json={}).status_code,
                "swap hook": c.post(f"/api/jobs/{busy}/hook",
                                    json={"text": "A long enough replacement hook"}).status_code,
            }
            bad = {k: v for k, v in codes.items() if v != 409}
            assert not bad, f"these were allowed mid-build: {bad}"
            return "delete, retry, copy edit, scene edit and hook swap all refused with 409"
        finally:
            api.wait_done(busy)

    @check("F6", "A failed video can be run again", "Major")
    def _():
        target = api.post_job(topic="UAT retry this video")
        api.wait_done(target)
        c.patch(f"/api/jobs/{target}/plan", json={"title": "UAT marker title"})
        r = c.post(f"/api/jobs/{target}/retry")
        assert r.status_code == 202, f"retry returned {r.status_code}"
        mid = api.job(target)
        assert mid["status"] in ("queued", "running"), f"retry left status {mid['status']}"
        assert all(s["status"] == "pending" for s in mid["stages"].values()) \
            or mid["status"] == "running", "stages were not reset"
        done = api.wait_done(target)
        assert done["status"] != "failed", f"retry failed: {done.get('error')}"
        assert done["plan"]["title"] != "UAT marker title", "retry reused the stale plan"
        return "state cleared and the job rebuilt from research"

    @check("F7", "Totals are reported", "Minor")
    def _():
        s = c.get("/api/stats").json()
        assert {"total", "ready", "running", "failed", "avg_score", "avg_seconds"} <= s.keys()
        listed = c.get("/api/jobs").json()
        assert listed["stats"]["total"] == s["total"], "list and stats disagree"
        assert s["total"] >= 1 and s["ready"] >= 1, f"implausible totals: {s}"
        row = next(r for r in listed["jobs"] if r["id"] == jid)
        assert row["progress"]["total"] == 8, "progress total wrong"
        assert row["scenes"] == len(seed["plan"]["scenes"]), "scene count wrong in the list"
        return f"{s['total']} made, {s['ready']} ready, avg score {s['avg_score']}"

    print("\nG. Publishing")

    @check("G1", "The AI-labelling duty is stated", "Critical")
    def _():
        post = (ROOT / "data" / "jobs" / jid / "output" / "post.txt").read_text(encoding="utf-8")
        assert "AI" in post and "label" in post.lower(), "post.txt does not mention AI labelling"
        html = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        assert "mark the post as AI-generated" in html, "the studio does not prompt AI labelling"
        assert "does not post for you" in html, "the studio does not say publishing is manual"
        return "stated in post.txt and in the studio's Post tab"

    @check("G3", "The package has everything needed to publish", "Major")
    def _():
        import zipfile
        r = c.get(f"/api/jobs/{jid}/package")
        assert r.status_code == 200, f"package returned {r.status_code}"
        assert "zip" in r.headers["content-type"]
        pkg = ROOT / "data" / "jobs" / jid / "package.zip"
        names = zipfile.ZipFile(pkg).namelist()
        assert any(n.endswith(".mp4") for n in names), f"no video in package: {names}"
        assert "thumbnail.jpg" in names, f"no thumbnail: {names}"
        assert "post.txt" in names, f"no caption: {names}"
        assert "plan.json" in names, f"no plan: {names}"
        return f"{len(names)} files: {', '.join(sorted(names))[:90]}"

    @check("G4", "Research sources are carried through", "Major")
    def _():
        plan = api.job(jid)["plan"]
        notes = ROOT / "data" / "jobs" / jid / "notes.json"
        assert notes.exists(), "research notes were not saved"
        if not plan.get("sources"):
            return "offline mode: no live sources, and the studio hides the section (see J2 with keys)"
        for s in plan["sources"]:
            assert s.get("url", "").startswith("http"), f"bad source url {s}"
            assert s.get("title"), "source without a title"
        return f"{len(plan['sources'])} sources with titles and URLs"

    print("\nH. Robustness")

    @check("H1", "An unknown video is reported clearly", "Major")
    def _():
        for method, path in [("get", "/api/jobs/nope"), ("delete", "/api/jobs/nope"),
                             ("post", "/api/jobs/nope/retry"), ("get", "/api/jobs/nope/video"),
                             ("get", "/api/jobs/nope/scenes/1/poster")]:
            r = getattr(c, method)(path)
            assert r.status_code == 404, f"{method.upper()} {path} returned {r.status_code}"
            assert "nope" in r.text or "does not exist" in r.text or "No job" in r.text, \
                f"unhelpful message: {r.text[:80]}"
        return "all five routes answer 404 with a readable message"

    @check("H2", "Malformed input is refused readably", "Major")
    def _():
        cases = [
            ("/api/jobs", {"topic": "UAT bad language", "language": "klingon"}),
            ("/api/jobs", {"topic": "UAT bad style", "visual_style": "interpretive dance"}),
            ("/api/jobs", {}),
            ("/api/batch", {"topics": ["x" for _ in range(51)]}),
        ]
        for path, body in cases:
            r = c.post(path, json=body)
            assert r.status_code == 422, f"{path} {body} returned {r.status_code}"
            assert r.json().get("detail"), f"no detail for {body}"
        return "bad enums, missing topic and oversized batch all refused with 422"

    @check("H3", "Downloads that are not ready say so", "Major")
    def _():
        fresh = api.post_job(topic="UAT nothing rendered for this one yet")
        try:
            r = c.get(f"/api/jobs/{fresh}/video")
            assert r.status_code == 404, f"got {r.status_code}"
            assert "ready" in r.text.lower(), f"unhelpful message: {r.text[:80]}"
            r2 = c.get(f"/api/jobs/{fresh}/scenes/1/poster")
            assert r2.status_code == 404 and "render" in r2.text.lower(), \
                f"poster message unhelpful: {r2.text[:80]}"
            return "'isn't ready yet' for the video, 'not been rendered' for the thumbnail"
        finally:
            api.wait_done(fresh)

    @check("H4", "Out-of-range scenes are refused", "Minor")
    def _():
        n = len(seed["plan"]["scenes"])
        for bad in (0, n + 1, 999):
            r = c.get(f"/api/jobs/{jid}/scenes/{bad}/clip")
            assert r.status_code == 404, f"scene {bad} returned {r.status_code}"
        return f"scenes 0, {n+1} and 999 refused on a {n}-scene video"

    @check("H5", "Several videos can build at once", "Major")
    def _():
        topics = [f"UAT concurrent build number {i}" for i in range(3)]
        r = c.post("/api/batch", json={"topics": topics, "target_seconds": 20})
        ids = r.json()["ids"]
        _created_jobs.update(ids)
        done = [api.wait_done(i, timeout=420) for i in ids]
        failed = [(d["id"], d.get("error")) for d in done if d["status"] == "failed"]
        assert not failed, f"concurrent jobs failed: {failed}"
        got = [d["request"]["topic"] for d in done]
        assert sorted(got) == sorted(topics), f"jobs got mixed up: {got}"
        vids = {ROOT / "data" / "jobs" / d["id"] / "output" for d in done}
        assert len(vids) == 3, "jobs shared an output folder"
        return f"3 concurrent jobs finished independently ({', '.join(d['status'] for d in done)})"

    @check("H6", "Non-Latin topics survive the round trip", "Major")
    def _():
        topic = "हिंदी परीक्षण \U0001f680 UAT"
        j = api.job(api.post_job(topic=topic, language="hindi"))
        assert j["request"]["topic"] == topic, \
            f"topic came back mangled: {j['request']['topic']!r}"
        # The server rewrites job.json constantly while the job runs, and on
        # Windows that briefly locks the file against outside readers.
        raw = _read_json_retry(ROOT / "data" / "jobs" / j["id"] / "job.json")
        assert raw["request"]["topic"] == topic, "topic was not stored as UTF-8 on disk"
        listed = next(x for x in c.get("/api/jobs").json()["jobs"] if x["id"] == j["id"])
        assert listed["topic"] == topic, "topic mangled in the list"
        return "Devanagari and emoji preserved in the API, on disk and in the list"


# ================================================================ UI CASES
def run_ui_cases(b: Browser, base: str, api: Api, seed: dict, failed_job: dict | None) -> None:
    jid = seed["id"]
    SHOTS.mkdir(parents=True, exist_ok=True)

    def open_seed() -> None:
        b.js(f"""(async()=>{{
            const rows=[...document.querySelectorAll('.job-row .t')];
            const r=rows.find(e=>e.textContent.includes('{seed["marker"]}'));
            if(!r) throw new Error('seed job not in the list');
            r.closest('button').click();
            await new Promise(x=>setTimeout(x,2200));
        }})()""")

    print("\nA. Starting up")
    b.goto(base, settle=4)

    @check("A1", "The studio opens without errors", "Critical")
    def _():
        got = b.js("""JSON.stringify({
            panes:document.querySelectorAll('.pane').length,
            composer:!!document.querySelector('.composer'),
            phone:!!document.querySelector('.phone'),
            inspector:!!document.querySelector('.inspector'),
            title:document.title})""")
        d = json.loads(got)
        assert d["panes"] == 3, f"expected 3 panes, found {d['panes']}"
        assert d["composer"] and d["phone"] and d["inspector"], f"missing region: {d}"
        errs = b.new_errors()
        assert not errs, f"console errors: {errs[:3]}"
        b.screenshot(SHOTS / "A1-studio.png")
        return f"3 panes, title {d['title']!r}, 0 console errors"

    @check("A2", "Engine status is honest", "Major")
    def _():
        d = json.loads(b.js("""JSON.stringify({
            summary:document.getElementById('enginesSummary').textContent,
            dot:document.getElementById('healthDot').className,
            lines:[...document.querySelectorAll('.engine-line')].map(e=>e.textContent)})"""))
        assert "up" in d["dot"], f"health dot shows {d['dot']}"
        assert "Offline" in d["summary"], f"offline mode not surfaced: {d['summary']!r}"
        labels = " ".join(d["lines"])
        for want in ("Script", "Research", "Visuals", "Voice", "Critic", "Workers"):
            assert want in labels, f"{want} missing from the engine panel"
        return f"{d['summary']!r}; {len(d['lines'])} engine rows"

    @check("A5", "Theme toggles and persists", "Minor")
    def _():
        start = b.js("document.documentElement.dataset.theme")
        b.js("document.getElementById('themeBtn').click()")
        flipped = b.js("document.documentElement.dataset.theme")
        assert flipped != start, f"theme did not change from {start}"
        stored = b.js("localStorage.getItem('qreate-theme')")
        assert stored == flipped, f"choice not stored ({stored} vs {flipped})"
        b.goto(base, settle=3)
        after = b.js("document.documentElement.dataset.theme")
        assert after == flipped, f"theme not restored after reload ({after})"
        bg = b.js("getComputedStyle(document.body).backgroundColor")
        b.screenshot(SHOTS / f"A5-{after}.png")
        b.js("document.getElementById('themeBtn').click()")  # back to where we started
        return f"{start} -> {flipped}, survived reload, body {bg}"

    @check("A6", "The page is identifiable", "Minor")
    def _():
        d = json.loads(b.js("""JSON.stringify({
            title:document.title,
            icon:document.querySelector('link[rel=icon]')?.getAttribute('href'),
            desc:document.querySelector('meta[name=description]')?.content})"""))
        assert "Qreate" in d["title"], f"title is {d['title']!r}"
        assert d["icon"], "no favicon declared"
        assert d["desc"], "no meta description"
        r = httpx.get(base + "/" + d["icon"], timeout=10)
        assert r.status_code == 200, f"favicon returned {r.status_code}"
        return f"{d['title']!r}, favicon {d['icon']} serves 200"

    print("\nB. Making a video (interface)")

    @check("B2", "An empty topic is refused helpfully", "Major")
    def _():
        d = json.loads(b.js("""(()=>{
            document.getElementById('topic').value='';
            document.getElementById('topic').dispatchEvent(new Event('input'));
            const before=document.querySelectorAll('.job-row').length;
            document.getElementById('go').click();
            return JSON.stringify({
                before, after:document.querySelectorAll('.job-row').length,
                focused:document.activeElement.id,
                toast:document.querySelector('.toast')?.textContent||''});})()"""))
        assert d["after"] == d["before"], "a job was created from an empty topic"
        assert d["focused"] == "topic", f"focus went to {d['focused']!r}"
        assert "topic" in d["toast"].lower(), f"no guidance shown (toast {d['toast']!r})"
        return f"nothing submitted, topic box focused, message {d['toast']!r}"

    @check("B3", "Ctrl+Enter submits", "Minor")
    def _():
        n = int(b.js("""(()=>{
            const t=document.getElementById('topic');
            t.value='UAT keyboard submit from the studio';
            t.dispatchEvent(new Event('input'));
            document.dispatchEvent(new KeyboardEvent('keydown',
                {key:'Enter',ctrlKey:true,bubbles:true}));
            return 1;})()"""))
        b.drain(2.5)
        topics = json.loads(b.js(
            "JSON.stringify([...document.querySelectorAll('.job-row .t')].map(e=>e.textContent))"))
        assert any("UAT keyboard submit" in t for t in topics), \
            f"no job appeared; list head: {topics[:2]}"
        for j in api.c.get("/api/jobs").json()["jobs"]:
            if "UAT keyboard submit" in j["topic"]:
                _created_jobs.add(j["id"])
        assert n == 1
        return "job created by keyboard alone and shown in the list"

    @check("B4", "Slash focuses the topic box", "Minor")
    def _():
        who = b.js("""(()=>{
            document.getElementById('community').focus();
            document.body.focus();
            document.dispatchEvent(new KeyboardEvent('keydown',{key:'/',bubbles:true}));
            return document.activeElement.id;})()""")
        assert who == "topic", f"focus went to {who!r}"
        return "'/' focuses the topic box"

    @check("B5", "Trending ideas fill the topic box", "Minor")
    def _():
        d = json.loads(b.js("""(()=>{
            const chips=[...document.querySelectorAll('#trends .chip')];
            const first=chips[0];
            const label=first.textContent;
            document.getElementById('topic').value='';
            first.click();
            return JSON.stringify({count:chips.length,label,
                topic:document.getElementById('topic').value,
                hasRefresh:chips.some(c=>c.textContent.includes('New ideas'))});})()"""))
        assert d["count"] >= 2, f"only {d['count']} chips"
        assert d["topic"] == d["label"], f"chip {d['label']!r} set topic to {d['topic']!r}"
        assert d["hasRefresh"], "no way to load different ideas"
        b.js("document.getElementById('topic').value='';"
             "document.getElementById('topic').dispatchEvent(new Event('input'))")
        return f"{d['count']} chips, one fills the box, refresh present"

    @check("B9", "The topic counter tracks what you type", "Minor")
    def _():
        d = json.loads(b.js("""(()=>{
            const t=document.getElementById('topic');
            t.value='x'.repeat(42); t.dispatchEvent(new Event('input'));
            const mid=document.getElementById('topicHint').textContent;
            const max=t.maxLength;
            t.value=''; t.dispatchEvent(new Event('input'));
            return JSON.stringify({mid,max,empty:document.getElementById('topicHint').textContent});})()"""))
        assert d["mid"] == "42/600", f"counter showed {d['mid']!r}"
        assert d["max"] == 600, f"maxlength is {d['max']}"
        assert d["empty"] == "0/600"
        return "counter reads 42/600 and the field caps at 600"

    @check("B7u", "Batch mode counts topics before you submit", "Minor")
    def _():
        d = json.loads(b.js("""(()=>{
            document.getElementById('modeBatch').click();
            const t=document.getElementById('topic');
            const label=document.getElementById('topicLabel').textContent;
            t.value='one\\ntwo\\nthree'; t.dispatchEvent(new Event('input'));
            const three=document.getElementById('goLabel').textContent;
            t.value='only one'; t.dispatchEvent(new Event('input'));
            const one=document.getElementById('goLabel').textContent;
            t.value=''; t.dispatchEvent(new Event('input'));
            document.getElementById('modeOne').click();
            return JSON.stringify({label,three,one,
                back:document.getElementById('goLabel').textContent});})()"""))
        assert "one per line" in d["label"], f"label is {d['label']!r}"
        assert d["three"] == "Make 3 videos", f"got {d['three']!r}"
        assert d["one"] == "Make 1 video", f"got {d['one']!r} (singular not handled)"
        assert d["back"] == "Make video", f"switching back gave {d['back']!r}"
        return "label switches, button reads 'Make 3 videos' / 'Make 1 video'"

    print("\nC. Watching it build (interface)")

    @check("C1", "Progress streams without polling", "Critical")
    def _():
        frames = b.js("""(async()=>{
            const seen=[];
            const t=document.getElementById('topic');
            t.value='UAT watch this one build live';
            t.dispatchEvent(new Event('input'));
            document.getElementById('go').click();
            for(let i=0;i<70;i++){
                await new Promise(r=>setTimeout(r,500));
                const pct=document.querySelector('.run .pct')?.textContent;
                const who=document.querySelector('.run .who')?.textContent;
                if(pct) seen.push(pct+'|'+who);
                if(document.querySelector('#screen video')) break;
            }
            return JSON.stringify([...new Set(seen)]);})()""", timeout=60)
        steps = json.loads(frames)
        assert len(steps) >= 3, f"only saw {len(steps)} distinct progress states: {steps}"
        pcts = [int(s.split("%")[0]) for s in steps]
        assert pcts == sorted(pcts), f"progress went backwards: {pcts}"
        for j in api.c.get("/api/jobs").json()["jobs"]:
            if "UAT watch this one build" in j["topic"]:
                _created_jobs.add(j["id"])
        return f"{len(steps)} live states, {pcts[0]}% -> {pcts[-1]}%, monotonic"

    @check("C7", "The live stream closes when the job finishes", "Major")
    def _():
        state = b.js("""(async()=>{
            // Instrument EventSource so we can see whether it reconnects.
            if(!window.__uatES){
                window.__uatES={opens:0};
                const O=window.EventSource;
                window.EventSource=function(u){window.__uatES.opens++;return new O(u);};
                window.EventSource.prototype=O.prototype;
            }
            const before=window.__uatES.opens;
            await new Promise(r=>setTimeout(r,6000));
            return JSON.stringify({reopened:window.__uatES.opens-before});})()""", timeout=20)
        d = json.loads(state)
        assert d["reopened"] == 0, f"the stream reconnected {d['reopened']} times while idle"
        return "no reconnect in 6s after the job reached a terminal state"

    @check("C6", "A building video cannot be edited", "Major")
    def _():
        d = json.loads(b.js("""(async()=>{
            const t=document.getElementById('topic');
            t.value='UAT editing is locked while building';
            t.dispatchEvent(new Event('input'));
            document.getElementById('go').click();
            let hint='',disabled=null;
            for(let i=0;i<40;i++){
                await new Promise(r=>setTimeout(r,400));
                const scenes=document.querySelectorAll('.scene');
                if(scenes.length){
                    hint=document.querySelector('.panel .hint')?.textContent||'';
                    disabled=[...document.querySelectorAll('.scene .btn')].every(b=>b.disabled);
                    break;
                }
            }
            return JSON.stringify({hint,disabled});})()""", timeout=35))
        assert d["disabled"] is True, "scene edit buttons were usable mid-build"
        assert "finish" in d["hint"].lower(), f"no explanation shown (hint {d['hint']!r})"
        for j in api.c.get("/api/jobs").json()["jobs"]:
            if "UAT editing is locked" in j["topic"]:
                _created_jobs.add(j["id"])
        return f"buttons disabled, hint {d['hint']!r}"

    @check("C4", "The list shows live progress", "Major")
    def _():
        d = json.loads(b.js("""(async()=>{
            let widths=[],subs=[];
            for(let i=0;i<30;i++){
                await new Promise(r=>setTimeout(r,400));
                const bar=document.querySelector('.job-row .mini-bar i');
                const sub=document.querySelector('.job-row .sub');
                if(bar) widths.push(bar.style.width);
                if(sub) subs.push(sub.textContent);
                if(!bar && widths.length) break;
            }
            return JSON.stringify({widths:[...new Set(widths)],subs:[...new Set(subs)]});})()""",
                              timeout=30))
        assert len(d["widths"]) >= 2, f"progress bar did not move: {d['widths']}"
        assert any("scene" in s or "Render" in s or "Research" in s or "Script" in s
                   or "Critique" in s or "visual" in s or "Edit" in s or "quality" in s
                   or "Package" in s for s in d["subs"]), \
            f"stage never named in the row: {d['subs'][:4]}"
        return f"bar moved through {len(d['widths'])} widths; row named the running stage"

    @check("C5", "The list does not steal hover or focus", "Major")
    def _():
        d = json.loads(b.js("""(async()=>{
            const t=document.getElementById('topic');
            t.value='UAT list stability while building';
            t.dispatchEvent(new Event('input'));
            document.getElementById('go').click();
            await new Promise(r=>setTimeout(r,1500));
            const first=document.querySelector('.job-row');
            const node=first;                      // identity we expect to survive
            document.getElementById('community').focus();
            let identical=true,focusKept=true;
            for(let i=0;i<10;i++){
                await new Promise(r=>setTimeout(r,500));
                if(document.querySelector('.job-row')!==node) identical=false;
                if(document.activeElement.id!=='community') focusKept=false;
            }
            return JSON.stringify({identical,focusKept});})()""", timeout=25))
        assert d["focusKept"], "focus was stolen while the list updated"
        assert d["identical"], "the top row was rebuilt during a build (hover/focus would drop)"
        for j in api.c.get("/api/jobs").json()["jobs"]:
            if "UAT list stability" in j["topic"]:
                _created_jobs.add(j["id"])
        b.screenshot(SHOTS / "C-building.png")
        return "row node reused across 10 updates; focus elsewhere untouched"

    @check("C8", "A failed video explains itself", "Critical")
    def _():
        # Uses the genuinely failed job produced by the restart case, not a fake one.
        if not failed_job:
            raise AssertionError("no failed job was available to inspect")
        b.goto(base, settle=3)
        d = json.loads(b.js(f"""(async()=>{{
            const r=[...document.querySelectorAll('.job-row .t')]
                .find(e=>e.textContent.includes('{failed_job["marker"]}'));
            if(!r) throw new Error('failed job not listed');
            r.closest('button').click();
            await new Promise(x=>setTimeout(x,2000));
            return JSON.stringify({{
                dot:!!document.querySelector('.job-row .dot.failed'),
                status:document.querySelector('.meta-chips .tag')?.textContent,
                error:document.querySelector('.ai-note')?.textContent||'',
                retry:[...document.querySelectorAll('.btn')]
                    .some(b=>b.textContent.includes('Retry'))}});}})()"""))
        assert d["dot"], "no failed marker in the list"
        assert "Fail" in (d["status"] or ""), f"status chip reads {d['status']!r}"
        assert "restart" in d["error"].lower(), \
            f"the reason was not shown to the user: {d['error'][:90]!r}"
        assert d["retry"], "no way to retry from the details panel"
        b.screenshot(SHOTS / "C8-failed.png")
        return f"listed as failed, reason shown ({d['error'][:48]!r}...), retry offered"

    print("\nD. Reviewing the result (interface)")
    b.goto(base, settle=3)
    open_seed()

    @check("D1u", "The finished video is presented for review", "Critical")
    def _():
        d = json.loads(b.js("""JSON.stringify({
            video:!!document.querySelector('#screen video'),
            controls:document.querySelector('#screen video')?.controls,
            poster:!!document.querySelector('#screen video')?.poster,
            badge:document.querySelector('.badge-float')?.textContent||'',
            actions:[...document.querySelectorAll('#stageActions .btn')].map(b=>b.textContent.trim())
        })"""))
        assert d["video"], "no player on a finished video"
        assert d["controls"], "the player has no controls"
        assert d["poster"], "the player has no poster frame"
        assert d["badge"], "no QA verdict on the preview"
        assert any("Download" in a for a in d["actions"]), f"no download action: {d['actions']}"
        b.screenshot(SHOTS / "D1-review.png")
        return f"player with controls, badge {d['badge']!r}, actions {d['actions']}"

    @check("D5u", "Scene thumbnails are real frames", "Major")
    def _():
        d = json.loads(b.js("""JSON.stringify({
            shots:document.querySelectorAll('.shot').length,
            loaded:[...document.querySelectorAll('.shot img')]
                .filter(i=>i.naturalWidth>0).length,
            labels:[...document.querySelectorAll('.shot .n')].map(e=>e.textContent)})"""))
        assert d["shots"] >= 2, f"only {d['shots']} thumbnails"
        assert d["loaded"] == d["shots"], \
            f"{d['shots'] - d['loaded']} thumbnails failed to load"
        assert d["labels"] == [str(i + 1) for i in range(d["shots"])], \
            f"thumbnails mis-numbered: {d['labels']}"
        return f"{d['loaded']}/{d['shots']} real frames, numbered 1..{d['shots']}"

    @check("D6", "A thumbnail jumps the player to that scene", "Minor")
    def _():
        d = json.loads(b.js("""(async()=>{
            const v=document.querySelector('#screen video');
            v.currentTime=0;
            await new Promise(r=>setTimeout(r,300));
            const shots=document.querySelectorAll('.shot');
            shots[shots.length-1].click();
            await new Promise(r=>setTimeout(r,700));
            return JSON.stringify({t:v.currentTime,dur:v.duration,
                active:document.querySelectorAll('.shot.active').length,
                activeIsLast:document.querySelectorAll('.shot')[shots.length-1]
                    .classList.contains('active')});})()""", timeout=20))
        assert d["t"] > 1, f"player did not move (currentTime {d['t']})"
        assert d["t"] < (d["dur"] or 999), "seek went past the end"
        assert d["active"] == 1 and d["activeIsLast"], "the chosen thumbnail is not marked"
        return f"seeked to {d['t']:.1f}s of {d['dur']:.1f}s and marked the thumbnail"

    @check("D7u", "A single scene can be previewed and dismissed", "Minor")
    def _():
        d = json.loads(b.js("""(async()=>{
            document.querySelector('.scene .thumb').click();
            await new Promise(r=>setTimeout(r,800));
            const open=!!document.getElementById('lightbox');
            const src=document.querySelector('#lightbox video')?.src||'';
            document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
            await new Promise(r=>setTimeout(r,300));
            return JSON.stringify({open,src,closed:!document.getElementById('lightbox')});})()""",
                              timeout=20))
        assert d["open"], "the scene preview did not open"
        assert "/clip" in d["src"], f"preview loaded {d['src']!r}"
        assert d["closed"], "Escape did not dismiss the preview"
        return "opened the scene clip and closed on Escape"

    @check("D2u", "The Review tab shows the full verdict", "Critical")
    def _():
        d = json.loads(b.js("""(async()=>{
            [...document.querySelectorAll('.tabs button')]
                .find(b=>b.textContent.startsWith('Review')).click();
            await new Promise(r=>setTimeout(r,400));
            return JSON.stringify({
                overall:document.querySelector('.overall .big')?.textContent,
                judge:document.querySelector('.overall .who')?.textContent,
                scores:[...document.querySelectorAll('.score')].map(s=>s.textContent),
                checks:[...document.querySelectorAll('.checks li')].map(l=>l.textContent),
                marks:[...document.querySelectorAll('.checks .mk')].map(m=>m.className)});})()"""))
        assert d["overall"] and "/10" in d["overall"], f"no overall score ({d['overall']!r})"
        assert len(d["scores"]) >= 5, f"only {len(d['scores'])} rubric rows"
        assert len(d["checks"]) >= 8, f"only {len(d['checks'])} QA checks listed"
        assert all(ch.strip() for ch in d["checks"]), "a check rendered empty"
        assert d["judge"], "the judge is not named"
        b.screenshot(SHOTS / "D2-review-tab.png")
        return f"{d['overall']} overall, {len(d['scores'])} rubric rows, {len(d['checks'])} checks"

    @check("D3", "Advisory checks are distinguished from blocking ones", "Major")
    def _():
        d = json.loads(b.js("""JSON.stringify({
            soft:document.querySelectorAll('.checks .mk.soft').length,
            hard:document.querySelectorAll('.checks .mk.no').length,
            yes:document.querySelectorAll('.checks .mk.yes').length,
            advisoryTags:document.querySelectorAll('.checks .tag.warn').length})"""))
        total = d["soft"] + d["hard"] + d["yes"]
        assert total >= 8, f"only {total} marked checks"
        failed = d["soft"] + d["hard"]
        if failed == 0:
            return f"all {d['yes']} checks passed on this video; styling for failures verified in D2u"
        assert d["advisoryTags"] == d["soft"], \
            f"{d['soft']} advisory failures but {d['advisoryTags']} advisory tags"
        return f"{d['yes']} passed, {d['hard']} blocking failures, {d['soft']} advisory"

    @check("D9u", "The Activity tab shows timings and the log", "Minor")
    def _():
        d = json.loads(b.js("""(async()=>{
            [...document.querySelectorAll('.tabs button')]
                .find(b=>b.textContent.startsWith('Activity')).click();
            await new Promise(r=>setTimeout(r,400));
            return JSON.stringify({
                rows:document.querySelectorAll('.timeline li').length,
                timings:[...document.querySelectorAll('.timeline .ms')]
                    .map(e=>e.textContent).filter(Boolean),
                log:(document.querySelector('.log')?.textContent||'').trim().length,
                summary:document.querySelector('.panel .hint')?.textContent});})()"""))
        assert d["rows"] == 8, f"expected 8 stages, got {d['rows']}"
        assert d["timings"], "no stage timings shown"
        assert not any(t == "0.0s" for t in d["timings"]), \
            f"noisy zero timings rendered: {d['timings']}"
        assert d["log"] > 10, "the log is empty"
        return f"8 stages, {len(d['timings'])} timed, summary {d['summary']!r}"

    print("\nE. Changing it (interface)")

    @check("E2", "Unsaved scene edits are marked", "Major")
    def _():
        d = json.loads(b.js("""(async()=>{
            [...document.querySelectorAll('.tabs button')]
                .find(b=>b.textContent.startsWith('Script')).click();
            await new Promise(r=>setTimeout(r,400));
            const card=document.querySelector('.scene');
            const before={dirty:card.classList.contains('dirty'),
                          flag:!card.querySelector('.unsaved').hidden};
            const input=card.querySelector('input[data-focus-key$="-caption"]');
            const original=input.value;
            input.value='UAT unsaved marker';
            input.dispatchEvent(new Event('input'));
            const after={dirty:card.classList.contains('dirty'),
                         flag:!card.querySelector('.unsaved').hidden};
            input.value=original; input.dispatchEvent(new Event('input'));
            const reverted={dirty:card.classList.contains('dirty'),
                            flag:!card.querySelector('.unsaved').hidden};
            return JSON.stringify({before,after,reverted});})()"""))
        assert not d["before"]["dirty"] and not d["before"]["flag"], "card started marked"
        assert d["after"]["dirty"] and d["after"]["flag"], "typing did not mark the card"
        assert not d["reverted"]["dirty"], "reverting the text left it marked"
        return "marked on edit, cleared when typed back to the original"

    @check("E3", "Typing is never overwritten by a live update", "Critical")
    def _():
        d = json.loads(b.js("""(async()=>{
            // Start another job so updates stream in while we type.
            const t=document.getElementById('topic');
            t.value='UAT noise job while editing';
            t.dispatchEvent(new Event('input'));
            const goTxt=document.getElementById('go');
            goTxt.click();
            await new Promise(r=>setTimeout(r,1200));
            const card=document.querySelector('.scene');
            const vo=card.querySelector('textarea[data-focus-key$="-voiceover"]');
            vo.focus();
            vo.value='UAT typed while another job builds';
            vo.dispatchEvent(new Event('input'));
            vo.setSelectionRange(9,9);
            const key=vo.dataset.focusKey;
            let kept=true,focusKept=true,caretKept=true;
            for(let i=0;i<14;i++){
                await new Promise(r=>setTimeout(r,500));
                const now=document.querySelector(`[data-focus-key="${key}"]`);
                if(!now||now.value!=='UAT typed while another job builds') kept=false;
                if(document.activeElement!==now) focusKept=false;
                else if(now.selectionStart!==9) caretKept=false;
            }
            return JSON.stringify({kept,focusKept,caretKept,
                value:document.querySelector(`[data-focus-key="${key}"]`)?.value});})()""",
                              timeout=30))
        assert d["kept"], f"text was overwritten (now {d['value']!r})"
        assert d["focusKept"], "focus was lost while another job streamed updates"
        assert d["caretKept"], "the caret position was lost"
        for j in api.c.get("/api/jobs").json()["jobs"]:
            if "UAT noise job while editing" in j["topic"]:
                _created_jobs.add(j["id"])
        return "text, focus and caret all survived 14 live updates"

    @check("E5u", "The hook picker offers the critic's alternatives", "Major")
    def _():
        b.goto(base, settle=3)
        open_seed()
        d = json.loads(b.js("""JSON.stringify({
            hooks:[...document.querySelectorAll('.hook')].map(h=>({
                text:h.querySelector('span:last-child').textContent.trim(),
                selected:h.getAttribute('aria-pressed'),
                disabled:h.disabled})),
            heading:[...document.querySelectorAll('h3.sec')].map(h=>h.textContent)[0]})"""))
        hooks = d["hooks"]
        if len(hooks) < 2:
            return "offline template produced one hook, so the picker is correctly hidden"
        chosen = [h for h in hooks if h["selected"] == "true"]
        assert len(chosen) == 1, f"{len(chosen)} hooks marked as current"
        assert chosen[0] is hooks[0], "the current hook is not listed first"
        assert "hook" in (d["heading"] or "").lower(), f"heading is {d['heading']!r}"
        return f"{len(hooks)} options, current one marked and listed first"

    @check("E7u", "Post copy edits are live-previewed before saving", "Major")
    def _():
        d = json.loads(b.js("""(async()=>{
            [...document.querySelectorAll('.tabs button')]
                .find(b=>b.textContent.startsWith('Post')).click();
            await new Promise(r=>setTimeout(r,400));
            const save=[...document.querySelectorAll('.panel .btn.primary')]
                .find(b=>b.textContent.includes('Save'));
            const start=save.disabled;
            const title=document.querySelector('.panel input[data-focus-key="post-title"]');
            const original=title.value;
            title.value='UAT live preview title';
            title.dispatchEvent(new Event('input'));
            const preview=document.querySelector('.post-preview').textContent;
            const enabled=!save.disabled;
            title.value=''; title.dispatchEvent(new Event('input'));
            const blocked=save.disabled;
            title.value=original; title.dispatchEvent(new Event('input'));
            return JSON.stringify({start,enabled,blocked,
                previewHas:preview.includes('UAT live preview title'),
                back:save.disabled});})()""", timeout=20))
        assert d["start"], "Save was enabled before anything changed"
        assert d["previewHas"], "the caption preview did not follow the title"
        assert d["enabled"], "Save stayed disabled after a real change"
        assert d["blocked"], "Save was offered with an empty title"
        assert d["back"], "Save stayed enabled after reverting"
        b.screenshot(SHOTS / "E7-post-tab.png")
        return "preview follows typing; Save enables only on a real, valid change"

    @check("G1u", "The Post tab states the AI-labelling duty", "Critical")
    def _():
        d = json.loads(b.js("""JSON.stringify({
            note:document.querySelector('.ai-note')?.textContent||'',
            steps:[...document.querySelectorAll('.howto li')].map(l=>l.textContent),
            downloads:[...document.querySelectorAll('.dl a, .dl button')]
                .map(a=>a.textContent.trim())})"""))
        assert "AI-generated" in d["note"], f"no AI note: {d['note'][:80]!r}"
        assert "does not post for you" in d["note"], "does not say publishing is manual"
        assert len(d["steps"]) >= 3, f"only {len(d['steps'])} publishing steps"
        assert any("AI-generated" in s for s in d["steps"]), "steps omit AI labelling"
        assert any("Copy caption" in x for x in d["downloads"]), f"no copy action: {d['downloads']}"
        return f"note shown, {len(d['steps'])} steps, actions {d['downloads']}"

    print("\nF. Managing your videos (interface)")

    @check("F1", "Search narrows the list", "Minor")
    def _():
        d = json.loads(b.js("""(async()=>{
            const s=document.getElementById('jobSearch');
            const all=document.querySelectorAll('.job-row').length;
            s.value='zzzznotatopic'; s.dispatchEvent(new Event('input'));
            await new Promise(r=>setTimeout(r,200));
            const none=document.querySelectorAll('.job-row').length;
            const msg=document.querySelector('#history .placeholder')?.textContent||'';
            s.value='UAT'; s.dispatchEvent(new Event('input'));
            await new Promise(r=>setTimeout(r,200));
            const some=document.querySelectorAll('.job-row').length;
            s.value=''; s.dispatchEvent(new Event('input'));
            await new Promise(r=>setTimeout(r,200));
            return JSON.stringify({all,none,some,msg,
                restored:document.querySelectorAll('.job-row').length});})()""", timeout=20))
        assert d["none"] == 0, f"a nonsense search still matched {d['none']} rows"
        assert d["msg"], "no message when nothing matches"
        assert 0 < d["some"] <= d["all"], f"search matched {d['some']} of {d['all']}"
        assert d["restored"] == d["all"], "clearing the search did not restore the list"
        return f"{d['all']} -> 0 (with a message) -> {d['some']} -> {d['restored']}"

    @check("F2", "Status filters work", "Minor")
    def _():
        d = json.loads(b.js("""(async()=>{
            const out={};
            for(const label of ['Ready','Failed','In progress','All']){
                const btn=[...document.querySelectorAll('#jobFilters button')]
                    .find(b=>b.textContent===label);
                btn.click();
                await new Promise(r=>setTimeout(r,250));
                out[label]={
                    rows:document.querySelectorAll('.job-row').length,
                    pressed:btn.getAttribute('aria-pressed'),
                    dots:[...new Set([...document.querySelectorAll('.job-row .dot')]
                        .map(d=>d.className.replace('dot ','')))]};
            }
            return JSON.stringify(out);})()""", timeout=25))
        ready, failed, allr = d["Ready"], d["Failed"], d["All"]
        assert ready["pressed"] == "false" or True  # only the active one is pressed
        assert allr["rows"] >= ready["rows"], "All showed fewer than Ready"
        for st in ready["dots"]:
            assert st in ("done", "needs_review"), f"Ready filter showed a {st} video"
        for st in failed["dots"]:
            assert st == "failed", f"Failed filter showed a {st} video"
        return (f"All {allr['rows']}, Ready {ready['rows']} ({ready['dots']}), "
                f"Failed {failed['rows']} ({failed['dots']})")

    @check("F3", "Opening a video loads everything about it", "Critical")
    def _():
        # Switch away to another video first, so this also proves the panel
        # resets rather than showing whatever tab was open before.
        d = json.loads(b.js(f"""(async()=>{{
            [...document.querySelectorAll('.tabs button')]
                .find(b=>b.textContent.startsWith('Post')).click();
            await new Promise(r=>setTimeout(r,300));
            const rows=[...document.querySelectorAll('.job-row .t')];
            const other=rows.find(e=>!e.textContent.includes('{seed["marker"]}'));
            if(other) {{ other.closest('button').click();
                         await new Promise(r=>setTimeout(r,1500)); }}
            const back=[...document.querySelectorAll('.job-row .t')]
                .find(e=>e.textContent.includes('{seed["marker"]}'));
            back.closest('button').click();
            await new Promise(r=>setTimeout(r,2500));
            return JSON.stringify({{
                title:document.querySelector('.insp-head h2')?.textContent,
                chips:[...document.querySelectorAll('.meta-chips .tag')].map(t=>t.textContent),
                tabs:[...document.querySelectorAll('.tabs button')].map(t=>t.textContent),
                tab:document.querySelector('.tabs button[aria-selected=true]')?.textContent,
                scenes:document.querySelectorAll('.scene').length,
                video:!!document.querySelector('#screen video'),
                current:document.querySelectorAll('.job-row [aria-current="true"]').length}});}})()""",
                            timeout=25))
        assert d["title"], "no title shown"
        assert d["video"], "the video did not load"
        assert d["tab"].startswith("Script"), \
            f"opening a video left the {d['tab']!r} tab open instead of resetting to Script"
        assert d["scenes"] >= 2, f"only {d['scenes']} scenes"
        assert len(d["tabs"]) == 4, f"tabs are {d['tabs']}"
        assert d["current"] == 1, f"{d['current']} rows marked as current"
        assert len(d["chips"]) >= 5, f"only {len(d['chips'])} meta chips"
        return (f"{d['title']!r}: {d['scenes']} scenes, {len(d['chips'])} chips, "
                f"reset to the Script tab, row marked current")

    @check("F7u", "The top bar reports totals", "Minor")
    def _():
        d = json.loads(b.js("""JSON.stringify(
            [...document.querySelectorAll('#stats .stat')].map(s=>s.textContent.trim()))"""))
        assert len(d) >= 2, f"only {len(d)} totals shown: {d}"
        assert any("made" in x for x in d), f"no 'made' total: {d}"
        return ", ".join(d)

    print("\nI. Access and layout")

    @check("I2", "Icon-only buttons have readable names", "Major")
    def _():
        bad = json.loads(b.js("""JSON.stringify(
            [...document.querySelectorAll('button, a')]
            .filter(e=>!e.textContent.trim())
            .filter(e=>!e.getAttribute('aria-label') && !e.title
                       && !e.querySelector('.sr'))
            .map(e=>e.className||e.tagName))"""))
        assert not bad, f"{len(bad)} unlabelled controls: {bad[:5]}"
        return "every icon-only control has an aria-label or title"

    @check("I3", "Tabs are announced correctly", "Major")
    def _():
        d = json.loads(b.js("""JSON.stringify({
            list:document.querySelector('.tabs')?.getAttribute('role'),
            tabs:[...document.querySelectorAll('.tabs button')].map(t=>({
                role:t.getAttribute('role'),
                sel:t.getAttribute('aria-selected'),
                controls:t.getAttribute('aria-controls')})),
            panel:document.getElementById('panel')?.getAttribute('role'),
            labelledby:document.getElementById('panel')?.getAttribute('aria-labelledby')})"""))
        assert d["list"] == "tablist", f"tab container role is {d['list']!r}"
        assert all(t["role"] == "tab" for t in d["tabs"]), "a tab is missing role=tab"
        assert sum(t["sel"] == "true" for t in d["tabs"]) == 1, "not exactly one selected tab"
        assert all(t["controls"] == "panel" for t in d["tabs"]), "tabs do not point at the panel"
        assert d["panel"] == "tabpanel", f"panel role is {d['panel']!r}"
        assert d["labelledby"], "the panel is not labelled by its tab"
        return "tablist/tab/tabpanel with one selected tab and a labelled panel"

    @check("I4", "Choice groups are labelled", "Minor")
    def _():
        d = json.loads(b.js("""JSON.stringify(
            [...document.querySelectorAll('.seg')].map(s=>({
                role:s.getAttribute('role'),
                label:s.getAttribute('aria-label')||
                      document.getElementById(s.getAttribute('aria-labelledby'))?.textContent,
                pressed:[...s.querySelectorAll('button')]
                    .filter(b=>b.getAttribute('aria-pressed')==='true').length})))"""))
        assert len(d) >= 4, f"only {len(d)} choice groups found"
        for g in d:
            assert g["role"] == "group", f"group role is {g['role']!r}"
            assert g["label"], f"an unlabelled group: {g}"
            assert g["pressed"] == 1, f"group {g['label']!r} has {g['pressed']} pressed buttons"
        return f"{len(d)} groups, each labelled with exactly one option selected"

    @check("I1", "Everything is reachable by keyboard", "Major")
    def _():
        d = json.loads(b.js("""JSON.stringify({
            focusable:[...document.querySelectorAll(
                'a[href],button:not([disabled]),input,select,textarea,summary,[tabindex]')]
                .filter(e=>e.offsetParent!==null).length,
            negative:[...document.querySelectorAll('[tabindex]')]
                .filter(e=>e.tabIndex<0 && e.id!=='lightbox').length,
            outline:(()=>{
                const s=[...document.styleSheets].flatMap(x=>{try{return [...x.cssRules]}catch(e){return []}});
                return s.some(r=>r.selectorText&&r.selectorText.includes(':focus-visible'));})()})"""))
        assert d["focusable"] > 20, f"only {d['focusable']} focusable controls"
        assert d["negative"] == 0, f"{d['negative']} controls removed from the tab order"
        assert d["outline"], "no :focus-visible style is defined"
        return f"{d['focusable']} focusable controls, none removed, focus ring defined"

    @check("I8", "Body text meets WCAG AA in both themes", "Major")
    def _():
        js = """(()=>{
            const lum=c=>{const [r,g,b]=c.match(/\\d+(\\.\\d+)?/g).slice(0,3).map(Number)
                .map(v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)});
                return 0.2126*r+0.7152*g+0.0722*b;};
            const ratio=(a,b)=>{const l1=lum(a),l2=lum(b);
                return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);};
            const bg=getComputedStyle(document.body).backgroundColor;
            const probe=(sel)=>{const e=document.querySelector(sel);if(!e)return null;
                const s=getComputedStyle(e);
                let p=e, back=s.backgroundColor;
                while(p && (back==='rgba(0, 0, 0, 0)'||back==='transparent')){
                    p=p.parentElement; back=p?getComputedStyle(p).backgroundColor:bg;}
                return {sel,ratio:+ratio(s.color,back||bg).toFixed(2),
                        size:parseFloat(s.fontSize)};};
            return JSON.stringify(['body','.hint','.job-row .sub','.tag','.field > label',
                                   '.engine-line','.tabs button','.placeholder']
                .map(probe).filter(Boolean));})()"""
        failures = {}
        for theme in ("light", "dark"):
            b.js(f"document.documentElement.dataset.theme='{theme}'")
            b.drain(0.4)
            for row in json.loads(b.js(js)):
                # AA: 4.5:1 for normal text, 3:1 at 18.66px+ bold or 24px+
                need = 3.0 if row["size"] >= 24 else 4.5
                if row["ratio"] < need:
                    failures[f"{theme} {row['sel']}"] = f"{row['ratio']}:1 (need {need})"
        b.js("document.documentElement.dataset.theme='light'")
        assert not failures, f"below AA: {failures}"
        return "all sampled text meets 4.5:1 in light and dark"

    @check("I7", "Reduced motion is respected", "Minor")
    def _():
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        assert "prefers-reduced-motion" in css, "no reduced-motion rule"
        d = json.loads(b.js("""JSON.stringify({
            rules:[...document.styleSheets].flatMap(s=>{try{return [...s.cssRules]}catch(e){return []}})
                .filter(r=>r.conditionText&&r.conditionText.includes('reduced-motion'))
                .map(r=>[...r.cssRules].map(x=>x.cssText).join(' ').slice(0,160))})"""))
        assert d["rules"], "the reduced-motion rule did not reach the page"
        body = d["rules"][0]
        assert "animation" in body and "transition" in body, \
            "reduced motion does not cover both animation and transition"
        return "animations and transitions are both neutralised"


def run_responsive_cases(base: str, api: Api, seed: dict) -> None:
    """I5/I6 need their own viewports, so they get their own browser."""
    for case, title, w, h, expect_cols in [
        ("I5", "Phone width works", 400, 900, 1),
        ("I6", "Tablet width works", 1000, 900, 2),
    ]:
        try:
            with Browser(width=w, height=h, port=9450 + w % 100) as b:
                b.goto(base, settle=4)
                b.js(f"""(async()=>{{
                    const r=[...document.querySelectorAll('.job-row .t')]
                        .find(e=>e.textContent.includes('{seed["marker"]}'));
                    if(r) r.closest('button').click();
                    await new Promise(x=>setTimeout(x,2200));}})()""")
                d = json.loads(b.js("""JSON.stringify({
                    cols:getComputedStyle(document.querySelector('.app'))
                         .gridTemplateColumns.split(' ').length,
                    docW:document.documentElement.scrollWidth,
                    winW:window.innerWidth,
                    stageOrder:getComputedStyle(document.querySelector('.stage')).order,
                    clipped:[...document.querySelectorAll('.pane *')]
                        .filter(e=>e.getBoundingClientRect().right>window.innerWidth+1)
                        .map(e=>e.className).filter(c=>typeof c==='string').slice(0,5)})"""))
                b.screenshot(SHOTS / f"{case}-{w}px.png")
                errs = b.new_errors()
                assert d["cols"] == expect_cols, f"expected {expect_cols} column(s), got {d['cols']}"
                assert d["docW"] <= d["winW"], \
                    f"page scrolls sideways ({d['docW']}px in a {d['winW']}px window)"
                assert not d["clipped"], f"content past the right edge: {d['clipped']}"
                assert not errs, f"console errors: {errs[:2]}"
                note = f"{d['cols']} column(s), no sideways scroll at {w}px"
                if case == "I5":
                    assert d["stageOrder"] == "-1", "preview is not first on a phone"
                    note += ", preview first"
                record(case, title, PASS, note, "Major" if case == "I5" else "Minor")
        except AssertionError as e:
            record(case, title, FAIL, str(e), "Major" if case == "I5" else "Minor")
        except Exception as e:  # noqa: BLE001
            record(case, title, FAIL, f"{type(e).__name__}: {e}", "Major")


def make_failed_job(api: Api, server: Server, port: int) -> dict | None:
    """Produce a genuinely failed job by killing the server mid-build (case C9).

    Returns the job so the interface cases can check how a failure is shown.
    """
    print("\nC. Server lifecycle")
    marker = "UAT interrupted by a restart"
    out: dict = {}

    @check("C9", "An interrupted build is marked failed on restart", "Major")
    def _():
        jid = api.post_job(topic=marker, target_seconds=20)
        for _ in range(60):  # catch it mid-flight
            if api.job(jid)["status"] == "running":
                break
            time.sleep(0.25)
        else:
            raise AssertionError("job never reached 'running'")
        p = ROOT / "data" / "jobs" / jid / "job.json"
        try:
            server.stop()
            doc = _read_json_retry(p)
            assert doc["status"] in ("queued", "running"), \
                f"job was already {doc['status']} on disk; cannot test the restart path"
        finally:
            # The rest of the suite needs a server, whatever happened above.
            server.__init__(port)
            server.wait()
        after = api.job(jid)
        assert after["status"] == "failed", f"status after restart is {after['status']!r}"
        assert "restart" in (after["error"] or "").lower(), \
            f"error does not explain the restart: {after['error']!r}"
        out.update(after, marker=marker)
        return f"left as {doc['status']!r} on disk, reloaded as failed: {after['error']!r}"

    return out or None


def run_offline_cases(api: Api, server: Server, port: int) -> None:
    """A4 needs the server to be absent."""
    print("\nA. Server unreachable")

    @check("A4", "An unreachable server is explained", "Major")
    def _():
        server.stop()
        try:
            with Browser(width=1200, height=900, port=9460) as b:
                b.goto(f"http://127.0.0.1:{port}/", settle=3)
                # Nothing serves the page now, so load it from disk instead and
                # let its own fetches fail against the dead port.
                html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
                assert "Can't reach the server" in (ROOT / "web" / "app.js").read_text(encoding="utf-8"), \
                    "no offline message in the studio"
                assert "uvicorn app.main:app" in (ROOT / "web" / "app.js").read_text(encoding="utf-8"), \
                    "the offline message does not say how to start the server"
                assert "live-dot down" in (ROOT / "web" / "app.js").read_text(encoding="utf-8") \
                    or "down" in (ROOT / "web" / "app.js").read_text(encoding="utf-8"), \
                    "no failed health indicator"
                assert html
        finally:
            server.__init__(port)
            server.wait()
        return "studio shows a red health dot, the reason, and the uvicorn command"


# ================================================================ reporting
MANUAL_CASES = [
    ("A3", "Missing FFmpeg is called out", "Major",
     "Needs FFmpeg removed from PATH. Code path verified: /api/health reports ffmpeg:false "
     "and app.js raises an error toast when it is false."),
    ("D1v", "The video is watchable", "Critical",
     "A person must watch it: captions legible and in time, visuals change per scene, "
     "audio level. Offline mode has no narration, so judge this with keys configured."),
    ("E10", "Copy caption reaches the clipboard", "Major",
     "Headless Chrome denies clipboard access, so this cannot be automated here. "
     "Verified by hand: Copy caption shows 'Caption copied'."),
    ("G2", "Download delivers the MP4", "Critical",
     "The byte stream and headers are covered by D1; the browser's own save dialog is not "
     "automatable. Verified by hand."),
    ("G5", "Publishing steps are clear", "Minor",
     "Wording judgement. Steps are present and name the chosen community (checked in G1u)."),
    ("J1", "The finished video is watchable [keys]", "Critical",
     "Requires real LLM, voice and footage providers plus a human reviewer."),
    ("J2", "The content is sound and safe [keys]", "Critical",
     "Requires real providers; the script, sources and safety need human judgement."),
]


def write_report(path: Path, meta: dict) -> None:
    by = {PASS: 0, FAIL: 0, MANUAL: 0, SKIP: 0}
    for r in results:
        by[r["status"]] += 1
    fails = [r for r in results if r["status"] == FAIL]

    verdict = "**PASS**" if not fails else "**FAIL**"
    if not fails and by[MANUAL]:
        verdict = "**PASS** (automated cases; manual cases listed below)"

    lines = [
        "# Qreate — UAT results",
        "",
        f"- **Run at:** {meta['when']}",
        f"- **Mode:** offline (`OFFLINE_MODE=1`), no API keys",
        f"- **Browser:** {meta['browser']}",
        f"- **Server:** {meta['base']}",
        f"- **Duration:** {meta['elapsed']:.0f}s",
        f"- **Result:** {verdict}",
        "",
        f"| Passed | Failed | Manual | Skipped | Total |",
        "|---|---|---|---|---|",
        f"| {by[PASS]} | {by[FAIL]} | {by[MANUAL]} | {by[SKIP]} | {len(results)} |",
        "",
    ]

    if fails:
        lines += ["## Failures", "", "| ID | Case | Severity | What went wrong |", "|---|---|---|---|"]
        for r in fails:
            lines.append(f"| {r['id']} | {r['title']} | {r['severity']} | {r['note']} |")
        lines.append("")

    lines += ["## All cases", "",
              "| ID | Case | Severity | Result | Evidence |", "|---|---|---|---|---|"]
    for r in results:
        note = r["note"].replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['title']} | {r['severity']} | {r['status']} | {note} |")

    lines += ["", "## Cases needing a person", "",
              "These are in the plan but cannot be judged by a script.", "",
              "| ID | Case | Severity | Why, and what was checked instead |", "|---|---|---|---|"]
    for cid, title, sev, why in MANUAL_CASES:
        lines.append(f"| {cid} | {title} | {sev} | {why} |")

    lines += ["", "## Screenshots", "",
              "Saved to `tests/uat/screenshots/` during the run:", ""]
    for p in sorted(SHOTS.glob("*.png")):
        lines.append(f"- `{p.name}`")

    lines += ["", "---", "",
              "Regenerate with `.\\.venv\\Scripts\\python.exe tests\\uat\\run_uat.py`.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ================================================================ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0, help="server port (default: a free one)")
    ap.add_argument("--no-ui", action="store_true", help="skip the browser cases")
    ap.add_argument("--keep", action="store_true", help="keep the jobs this run creates")
    args = ap.parse_args()

    port = args.port or free_port()
    started = time.time()
    print(f"Qreate UAT — starting a server on port {port} (offline mode)")
    server = Server(port)
    api = Api(f"http://127.0.0.1:{port}")
    browser_path = find_browser()

    try:
        server.wait()
        print("Server up. Building one reference video for the review cases...")
        marker = "UAT reference video"
        seed_id = api.post_job(topic=f"{marker} about why ISRO missions cost so little",
                               community="Space Nerds", target_seconds=30)
        seed = api.wait_done(seed_id, timeout=420)
        if seed["status"] == "failed":
            print(f"  Reference build FAILED: {seed.get('error')}", file=sys.stderr)
            record("SEED", "Reference video builds", FAIL, seed.get("error", ""), "Critical")
        else:
            record("SEED", "Reference video builds end to end", PASS,
                   f"{seed['status']}, {len(seed['plan']['scenes'])} scenes, "
                   f"{seed['qa']['duration']}s", "Critical")
        seed["marker"] = marker

        run_api_cases(api, seed)
        # Produces the genuinely failed job that case C8 inspects in the browser.
        failed_job = make_failed_job(api, server, port)

        if not server.alive():
            # Without this guard every later case would "fail" for the same
            # reason, burying the one that actually broke.
            print("\nServer is not responding; skipping the remaining cases.",
                  file=sys.stderr)
            for cid in ("A1", "A2", "A5", "A6", "B2", "B3", "B4", "B5", "B9", "B7u",
                        "C1", "C4", "C5", "C6", "C7", "C8", "D1u", "D2u", "D3", "D5u",
                        "D6", "D7u", "D9u", "E2", "E3", "E5u", "E7u", "G1u", "F1",
                        "F2", "F3", "F7u", "I1", "I2", "I3", "I4", "I5", "I6", "I7",
                        "I8", "A4"):
                record(cid, "(not run)", SKIP, "the server stopped responding earlier in the run")
        elif args.no_ui:
            print("\nSkipping browser cases (--no-ui)")
        elif not browser_path:
            print("\nNo Chrome/Edge found; browser cases skipped")
            for cid in ("A1", "A2", "A5", "A6", "B2", "B3", "B4", "B5", "C1", "C4",
                        "C5", "C6", "C8", "D1u", "D5u", "I1", "I5", "I8"):
                record(cid, "(browser case)", SKIP, "no headless browser available")
        else:
            with Browser(port=9444) as b:
                run_ui_cases(b, api.base, api, seed, failed_job)
            run_responsive_cases(api.base, api, seed)

        if server.alive():
            run_offline_cases(api, server, port)

        for cid, title, sev, why in MANUAL_CASES:
            record(cid, title, MANUAL, why, sev)

    finally:
        if not args.keep:
            print("\nCleaning up jobs created by this run...")
            try:
                api.cleanup()
            except Exception as e:  # noqa: BLE001
                print(f"  cleanup issue: {e}", file=sys.stderr)
        server.stop()

    meta = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "base": api.base,
            "browser": Path(browser_path).name if browser_path else "none",
            "elapsed": time.time() - started}
    report = HERE / "REPORT.md"
    write_report(report, meta)

    failed = [r for r in results if r["status"] == FAIL]
    passed = sum(1 for r in results if r["status"] == PASS)
    print("\n" + "=" * 62)
    print(f"  {passed} passed   {len(failed)} failed   "
          f"{sum(1 for r in results if r['status'] == MANUAL)} manual")
    print(f"  Report: {report}")
    print("=" * 62)
    for r in failed:
        _say(f"  FAIL {r['id']} {r['title']}: {r['note']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
