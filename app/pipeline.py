"""The orchestrator: runs every stage, records progress, caches per stage.

Stage outputs are written into the job folder, so a scene edit only redoes the
work for that scene and then re-assembles the reel.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .agents import critic, scriptwriter
from .jobs import JobStore
from .media import captions, compose, ff
from .media.qa import run_qa
from .models import Critique, JobRequest, SceneEdit, ScenePlan
from .providers import research as research_mod
from .providers import visuals, voice

log = logging.getLogger("qreate.pipeline")


def _seed(job_id: str, i: int) -> int:
    return int(hashlib.md5(f"{job_id}-{i}".encode()).hexdigest(), 16) % 1_000_000


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "reel"


# ------------------------------------------------------------------ scene work
def _scene_dir(d: Path, i: int) -> Path:
    sd = d / "scenes" / f"{i:02d}"
    sd.mkdir(parents=True, exist_ok=True)
    return sd


def build_scene_assets(job_id: str, d: Path, req: JobRequest, plan: ScenePlan, i: int,
                       force_visual: bool = False, force_voice: bool = False, variant: int = 0) -> dict:
    sd = _scene_dir(d, i)
    meta_p = sd / "assets.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    scene = plan.scenes[i]
    if force_visual or "visual" not in meta or not Path(meta["visual"]["path"]).exists():
        meta["visual"] = visuals.get_visual(scene, req.visual_style, sd, i, _seed(job_id, i), variant)
        meta["variant"] = variant
    if force_voice or "voice" not in meta or not Path(meta["voice"]["path"]).exists():
        meta["voice"] = voice.synthesize(scene.voiceover, req.language, sd / "voice")
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def render_one(d: Path, req: JobRequest, plan: ScenePlan, i: int, meta: dict) -> Path:
    sd = _scene_dir(d, i)
    scene = plan.scenes[i]
    is_last = i == len(plan.scenes) - 1
    dur = meta["voice"]["duration"] + (0.9 if is_last else 0.3)
    out = sd / "scene.mp4"
    key = hashlib.md5(json.dumps([meta, scene.caption, round(dur, 3), req.community]).encode()).hexdigest()
    key_p = sd / "render.key"
    if out.exists() and key_p.exists() and key_p.read_text() == key:
        return out  # cached
    cap_dir = sd / "captions"
    shutil.rmtree(cap_dir, ignore_errors=True)
    states = captions.render_scene_captions(scene.caption, meta["voice"]["words"], dur, cap_dir,
                                            community=req.community if i == 0 else "")
    lst = captions.write_concat_list(states, sd / "captions.txt")
    compose.render_scene(i, meta["visual"], meta["voice"]["path"], lst, dur, out)
    key_p.write_text(key, encoding="utf-8")
    return out


# ------------------------------------------------------------------ stages
def _assets_all(store: JobStore, job_id: str, d: Path, req: JobRequest, plan: ScenePlan) -> list[dict]:
    store.stage(job_id, "assets", "running", f"0/{len(plan.scenes)} scenes")
    metas: list[dict | None] = [None] * len(plan.scenes)
    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(build_scene_assets, job_id, d, req, plan, i): i for i in range(len(plan.scenes))}
        for f in futs:
            i = futs[f]
            metas[i] = f.result()
            done += 1
            store.stage(job_id, "assets", "running", f"{done}/{len(plan.scenes)} scenes")
    engines = sorted({m["voice"]["engine"] for m in metas})
    sources = sorted({m["visual"]["source"].split(" by ")[0].replace(" (cached)", "") for m in metas})
    store.stage(job_id, "assets", "done", f"Voice: {', '.join(engines)} · Visuals: {', '.join(sources)}")
    store.update(job_id, scene_assets=[{"visual_source": m["visual"]["source"], "voice_engine": m["voice"]["engine"],
                                        "duration": round(m["voice"]["duration"], 2)} for m in metas])
    return metas


def _render_all(store: JobStore, job_id: str, d: Path, req: JobRequest, plan: ScenePlan, metas: list[dict]) -> list[Path]:
    store.stage(job_id, "render", "running", f"0/{len(plan.scenes)} scenes")
    clips: list[Path | None] = [None] * len(plan.scenes)
    done = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(render_one, d, req, plan, i, metas[i]): i for i in range(len(plan.scenes))}
        for f in futs:
            clips[futs[f]] = f.result()
            done += 1
            store.stage(job_id, "render", "running", f"{done}/{len(plan.scenes)} scenes")
    store.stage(job_id, "render", "done", f"{len(clips)} scenes rendered")
    return clips  # type: ignore[return-value]


def _finish(store: JobStore, job_id: str, d: Path, req: JobRequest, plan: ScenePlan,
            crit: Critique | None, clips: list[Path]) -> None:
    store.stage(job_id, "assemble", "running")
    out_dir = d / "output"
    out_dir.mkdir(exist_ok=True)
    final = out_dir / f"qreate-{_slug(plan.title)}.mp4"
    for old in out_dir.glob("qreate-*.mp4"):
        old.unlink()
    compose.assemble(clips, final, d, seed=job_id)
    thumb = compose.thumbnail(final, out_dir / "thumbnail.jpg")
    store.stage(job_id, "assemble", "done", f"{ff.duration(str(final)):.1f}s · 1080×1920 · -14 LUFS")

    store.stage(job_id, "qa", "running")
    qa = run_qa(final, plan, crit, req.target_seconds)
    n_ok = sum(c["pass"] for c in qa["checks"])
    store.stage(job_id, "qa", "done" if qa["passed"] else "failed", f"{n_ok}/{len(qa['checks'])} checks passed")

    store.stage(job_id, "package", "running")
    post = [
        plan.title, "", plan.description, "", " ".join(plan.hashtags), "",
        "Made with AI (Qreate). Please label as AI-generated when posting.",
    ]
    if plan.sources:
        post += ["", "Sources:"] + [f"- {s['title']}: {s['url']}" for s in plan.sources]
    (out_dir / "post.txt").write_text("\n".join(post), encoding="utf-8")
    (out_dir / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    pkg = d / "package.zip"
    with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as z:
        for f in out_dir.iterdir():
            z.write(f, f.name)
    store.stage(job_id, "package", "done", "Video, thumbnail, caption and hashtags ready")
    store.update(job_id, qa=qa, outputs={"video": str(final), "thumbnail": str(thumb), "package": str(pkg)},
                 status="done" if qa["passed"] else "needs_review")
    store.log(job_id, f"Finished: {final.name} ({'QA passed' if qa['passed'] else 'QA flagged issues'})")


# ------------------------------------------------------------------ entry points
def run_job(store: JobStore, job_id: str) -> None:
    job = store.get(job_id)
    req = JobRequest(**job["request"])
    d = store.dir(job_id)
    store.update(job_id, status="running")
    try:
        store.stage(job_id, "research", "running")
        notes = research_mod.research(req.topic)
        (d / "notes.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
        store.stage(job_id, "research", "done", f"{len(notes)} sources" if notes else "No live sources (offline); staying general")

        store.stage(job_id, "script", "running")
        plan = scriptwriter.write(req, notes)
        store.stage(job_id, "script", "done", f"{len(plan.scenes)} scenes by {plan.generated_by}")
        store.update(job_id, plan=plan.model_dump())

        store.stage(job_id, "critic", "running")
        crit = critic.judge(req, notes, plan)
        rounds = 0
        while crit.overall < config.CRITIC_THRESHOLD and rounds < config.CRITIC_MAX_ROUNDS and crit.judged_by != "heuristic":
            rounds += 1
            store.log(job_id, f"Critic scored {crit.overall}/10, rewriting (round {rounds})")
            plan = scriptwriter.revise(req, notes, plan, crit.issues)
            crit = critic.judge(req, notes, plan)
        crit.rounds = rounds
        store.stage(job_id, "critic", "done", f"{crit.overall}/10 after {rounds} rewrite(s) · {crit.judged_by}")
        store.update(job_id, plan=plan.model_dump(), critique=crit.model_dump())
        (d / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        metas = _assets_all(store, job_id, d, req, plan)
        clips = _render_all(store, job_id, d, req, plan, metas)
        _finish(store, job_id, d, req, plan, crit, clips)
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        running = [k for k, v in (store.get(job_id) or {}).get("stages", {}).items() if v["status"] == "running"]
        for k in running:
            store.stage(job_id, k, "failed", str(e)[:300])
        store.update(job_id, status="failed", error=f"{type(e).__name__}: {str(e)[:500]}")
        store.log(job_id, traceback.format_exc()[-1500:])


def regenerate_scene(store: JobStore, job_id: str, scene_idx: int, edit: SceneEdit) -> None:
    """Edit or re-roll one scene, then re-render only that scene and re-assemble."""
    job = store.get(job_id)
    req = JobRequest(**job["request"])
    d = store.dir(job_id)
    plan = ScenePlan.model_validate(job["plan"])
    crit = Critique.model_validate(job["critique"]) if job.get("critique") else None
    scene = plan.scenes[scene_idx]

    force_voice = edit.voiceover is not None and edit.voiceover.strip() != scene.voiceover
    visual_changed = any(x is not None for x in (edit.visual_query, edit.visual_prompt, edit.visual_mode))
    if edit.voiceover is not None:
        scene.voiceover = edit.voiceover.strip()
        if scene_idx == 0:
            plan.hook = scene.voiceover
    if edit.caption is not None:
        scene.caption = edit.caption.strip()
    if edit.visual_query is not None:
        scene.visual.query = edit.visual_query.strip()
    if edit.visual_prompt is not None:
        scene.visual.prompt = edit.visual_prompt.strip()
    if edit.visual_mode is not None:
        scene.visual.mode = edit.visual_mode
    reroll = not (force_voice or visual_changed or edit.caption is not None)

    store.update(job_id, status="running", plan=plan.model_dump(), error=None)
    for k in ("render", "assemble", "qa", "package"):
        store.stage(job_id, k, "pending", "")
    try:
        store.stage(job_id, "assets", "running", f"Scene {scene_idx + 1}")
        meta_p = _scene_dir(d, scene_idx) / "assets.json"
        prev_variant = json.loads(meta_p.read_text(encoding="utf-8")).get("variant", 0) if meta_p.exists() else 0
        build_scene_assets(job_id, d, req, plan, scene_idx, force_visual=visual_changed or reroll,
                           force_voice=force_voice, variant=prev_variant + 1 if reroll else 0)
        store.stage(job_id, "assets", "done", f"Scene {scene_idx + 1} updated")
        metas = [build_scene_assets(job_id, d, req, plan, i) for i in range(len(plan.scenes))]
        clips = _render_all(store, job_id, d, req, plan, metas)
        store.log(job_id, f"Scene {scene_idx + 1} regenerated")
        _finish(store, job_id, d, req, plan, crit, clips)
    except Exception as e:  # noqa: BLE001
        log.exception("regenerate failed")
        store.update(job_id, status="failed", error=f"{type(e).__name__}: {str(e)[:500]}")
