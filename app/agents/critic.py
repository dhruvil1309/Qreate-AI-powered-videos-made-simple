"""Critic agent: LLM-as-judge with an explicit rubric, plus a heuristic fallback.

The pipeline loops write -> judge -> revise until the overall score reaches
CRITIC_THRESHOLD or CRITIC_MAX_ROUNDS is hit.
"""
from __future__ import annotations

import json
import logging

from .. import config
from ..models import Critique, JobRequest, ScenePlan
from ..providers.llm import LLMUnavailable, chat_json
from .scriptwriter import WORDS_PER_SECOND

log = logging.getLogger("qreate.critic")

RUBRIC = {
    "hook": "Would a scrolling viewer stop in the first 2 seconds?",
    "clarity": "Is every scene one clear, easy idea in short spoken sentences?",
    "accuracy": "Are all factual claims supported by the research notes (no invented stats)?",
    "pacing": "Does length fit the target and does each scene lead to the next?",
    "community_fit": "Does tone and language fit the target community and language setting?",
    "safety": "Is it safe, respectful and free of harmful or misleading advice?",
}

SYSTEM = (
    "You are a strict short-video editor for Qoneqt. Score the draft reel 0-10 on each rubric item, "
    "compute 'overall' as the average, and list concrete, actionable fixes (max 6). "
    'Return ONLY JSON: {"scores": {"hook": n, "clarity": n, "accuracy": n, "pacing": n, '
    '"community_fit": n, "safety": n}, "overall": n, "issues": ["..."]}'
)


def judge(req: JobRequest, notes: list[dict], plan: ScenePlan) -> Critique:
    if not config.CRITIC_USE_LLM:
        return heuristic(req, plan)
    user = (
        "RUBRIC:\n" + "\n".join(f"- {k}: {v}" for k, v in RUBRIC.items())
        + f"\n\nTARGET: {req.target_seconds}s, community '{req.community}', language {req.language}, tone {req.tone}"
        + "\n\nRESEARCH NOTES:\n" + ("\n".join(f"- {n['snippet'][:400]}" for n in notes) or "(none)")
        + "\n\nDRAFT:\n" + json.dumps(plan.model_dump(exclude={"sources", "generated_by"}), ensure_ascii=False)
    )
    try:
        data, provider = chat_json(SYSTEM, user, temperature=0.2)
        scores = {k: float(max(0, min(10, data.get("scores", {}).get(k, 0)))) for k in RUBRIC}
        overall = round(sum(scores.values()) / len(scores), 2)
        return Critique(scores=scores, overall=overall, issues=[str(i) for i in data.get("issues", [])][:6], judged_by=provider)
    except (LLMUnavailable, ValueError, TypeError, KeyError) as e:
        log.info("LLM judge unavailable (%s); using heuristic critic", e)
        return heuristic(req, plan)


def heuristic(req: JobRequest, plan: ScenePlan) -> Critique:
    issues = []
    hook_words = len(plan.hook.split())
    hook = 9.0 if hook_words <= 14 else max(4.0, 9 - (hook_words - 14) * 0.5)
    if hook_words > 14:
        issues.append(f"Hook is {hook_words} words; cut it to 14 or fewer.")
    if plan.hook.lower().startswith(("hi", "hello", "in this video", "welcome")):
        hook -= 3
        issues.append("Hook opens with a greeting; lead with the surprise instead.")

    total_words = sum(len(s.voiceover.split()) for s in plan.scenes)
    target_words = req.target_seconds * WORDS_PER_SECOND
    ratio = total_words / target_words if target_words else 1
    pacing = 9.0 if 0.7 <= ratio <= 1.25 else 6.0
    if pacing < 9:
        issues.append(f"Script is {total_words} words; aim for about {int(target_words)} for {req.target_seconds}s.")

    long_caps = [s.id for s in plan.scenes if len(s.caption.split()) > 6]
    clarity = 9.0 - len(long_caps)
    if long_caps:
        issues.append(f"Shorten captions in scenes {long_caps} to 6 words or fewer.")
    long_lines = [s.id for s in plan.scenes if len(s.voiceover.split()) > 40]
    if long_lines:
        clarity -= 1
        issues.append(f"Split long voiceover in scenes {long_lines}.")

    cta_ok = bool(plan.cta) or "follow" in plan.scenes[-1].voiceover.lower()
    community_fit = 8.0 if cta_ok else 6.5
    if not cta_ok:
        issues.append("End with a call to action for Qoneqt.")
    accuracy = 8.0 if plan.sources else 7.0
    scores = {"hook": hook, "clarity": max(clarity, 3), "accuracy": accuracy, "pacing": pacing, "community_fit": community_fit, "safety": 9.0}
    return Critique(scores=scores, overall=round(sum(scores.values()) / len(scores), 2), issues=issues, judged_by="heuristic")
