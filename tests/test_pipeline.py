"""Run with:  OFFLINE_MODE=1 pytest -q

The LLM is mocked so these tests check the real pipeline logic (plan
validation, critic loop, captions, rendering, QA) without API keys.
"""
import os

os.environ.setdefault("OFFLINE_MODE", "1")

from pathlib import Path  # noqa: E402

from app import config  # noqa: E402
from app.agents import critic, scriptwriter  # noqa: E402
from app.jobs import store  # noqa: E402
from app.media import captions  # noqa: E402
from app.models import JobRequest, ScenePlan  # noqa: E402
from app.pipeline import run_job  # noqa: E402

LLM_PLAN = {
    "title": "Why ISRO does space on a budget",
    "hook_options": ["Mars for less than a movie?", "ISRO's secret is frugal"],
    "hook": "ignored - replaced by scene 1",
    "scenes": [
        {"id": 9, "voiceover": "India reached Mars for less than a Hollywood space movie.", "caption": "Mars on a budget",
         "visual": {"mode": "ai_image", "prompt": "orange planet with a small satellite, cinematic"}},
        {"id": 9, "voiceover": "The trick? Reuse proven parts and test smart, not expensive.", "caption": "Reuse, test smart",
         "visual": {"mode": "stock", "query": "rocket launch"}},
        {"id": 9, "voiceover": "Which ISRO mission should we explain next? Comment below and follow on Qoneqt.",
         "caption": "Your pick?", "visual": {"mode": "weird", "query": "night sky"}},
    ],
    "cta": "Comment and follow",
    "description": "How ISRO keeps missions affordable.",
    "hashtags": ["ISRO", "#space", "#Space", "Qoneqt"],
}

REQ = JobRequest(topic="Why ISRO missions cost so little", community="Space Nerds", target_seconds=20)


def test_llm_json_becomes_valid_plan(monkeypatch):
    monkeypatch.setattr(scriptwriter, "chat_json", lambda *a, **k: (LLM_PLAN, "mock"))
    plan = scriptwriter.write(REQ, [])
    assert [s.id for s in plan.scenes] == [1, 2, 3]
    assert plan.hook == plan.scenes[0].voiceover
    assert plan.scenes[2].visual.mode == "stock"  # invalid mode repaired
    assert plan.hashtags == ["#ISRO", "#space", "#Qoneqt"]  # normalised + deduped
    assert plan.generated_by == "mock"


def test_offline_plan_without_llm():
    plan = scriptwriter.offline_plan(REQ, [])
    assert len(plan.scenes) >= 4
    assert "Qoneqt" in plan.cta


def test_heuristic_critic_flags_long_hook():
    plan = ScenePlan.model_validate({**LLM_PLAN, "hook": " ".join(["word"] * 20),
                                     "scenes": [{**s, "id": i} for i, s in enumerate(LLM_PLAN["scenes"], 1)]})
    plan.scenes[2].visual.mode = "stock"
    c = critic.heuristic(REQ, plan)
    assert any("Hook" in i for i in c.issues)


def test_captions_cover_scene_duration(tmp_path: Path):
    words = [{"word": w, "start": 0.3 + i * 0.4, "end": 0.6 + i * 0.4} for i, w in enumerate("one two three four five".split())]
    states = captions.render_scene_captions("Test caption", words, 3.0, tmp_path)
    assert abs(sum(d for _, d in states) - 3.0) < 0.01
    assert all(Path(p).exists() for p, _ in states)


def test_full_pipeline_with_critic_rewrite(monkeypatch):
    calls = {"judge": 0}
    monkeypatch.setattr(scriptwriter, "chat_json", lambda *a, **k: (LLM_PLAN, "mock"))

    def fake_judge(system, user, temperature=0.2):
        calls["judge"] += 1
        score = 6 if calls["judge"] == 1 else 9  # first draft fails, rewrite passes
        return {"scores": {k: score for k in critic.RUBRIC}, "issues": ["Sharper hook"]}, "mock"

    monkeypatch.setattr(critic, "chat_json", fake_judge)
    monkeypatch.setattr(config, "CRITIC_USE_LLM", True)  # independent of the local .env
    job = store.create(REQ)
    run_job(store, job["id"])
    j = store.get(job["id"])
    assert j["status"] in ("done", "needs_review"), j["error"]
    assert j["critique"]["rounds"] == 1 and j["critique"]["overall"] == 9
    assert Path(j["outputs"]["video"]).exists()
    assert j["qa"]["checks"][0]["pass"]  # 1080x1920
