"""Script agent: topic + research -> validated ScenePlan (hook, script, scene plan)."""
from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from ..models import JobRequest, ScenePlan
from ..providers.llm import LLMUnavailable, chat_json

log = logging.getLogger("qreate.script")

WORDS_PER_SECOND = 2.4

LANGUAGE_RULES = {
    "english": "Write voiceover and captions in simple, conversational Indian English.",
    "hinglish": (
        "Write voiceover and captions in natural Hinglish (Hindi-English mix) using ROMAN script only, "
        "the way young Indians text, e.g. 'Kal ka lecture yaad hai? Nahi na.' Never use Devanagari."
    ),
    "hindi": "Write voiceover and captions in simple spoken Hindi using Devanagari script.",
}

SYSTEM = """You are the head writer for Qoneqt, a community-first Indian social platform.
You write short vertical videos (reels) for the Qoneqt Global Feed.

Rules for a great Qoneqt reel:
- Scene 1's voiceover IS the hook. It must stop the scroll in under 2 seconds: a surprising fact,
  a bold claim, a relatable pain or a direct question. Max 14 words. No greetings, no "In this video".
- One idea per scene. Short spoken sentences. Every scene earns the next one.
- Use ONLY facts supported by the research notes. If a fact is not in the notes, keep it general
  rather than inventing numbers, names or dates.
- Speak to the target community in their language and tone. Be useful, specific and positive.
- The last scene is a call to action that invites comments or follows on Qoneqt.
- Captions are punchy on-screen headlines (2-6 words), not a copy of the voiceover.
- Visuals: for each scene choose "stock" (real-world footage; give a 2-4 word English search query)
  or "ai_image" (conceptual or impossible shots; give a detailed English image prompt, no text in image).
- Safe for a general audience. No medical, legal or financial advice beyond general education.

Return ONLY JSON with this exact shape:
{
  "title": "post title, max 70 chars",
  "hook_options": ["3 alternative hooks"],
  "hook": "the chosen hook (same text as scene 1 voiceover)",
  "scenes": [
    {"id": 1, "voiceover": "...", "caption": "...",
     "visual": {"mode": "stock" | "ai_image", "query": "...", "prompt": "..."}}
  ],
  "cta": "call to action line",
  "description": "Qoneqt post caption, 1-2 sentences",
  "hashtags": ["#tag", "..."]
}"""


def _brief(req: JobRequest, notes: list[dict]) -> str:
    n_scenes = max(4, min(9, round(req.target_seconds / 6.5)))
    words = int(req.target_seconds * WORDS_PER_SECOND)
    style = {
        "mix": "Mix stock footage and AI images, whichever fits each scene best.",
        "stock": "Prefer 'stock' for every scene.",
        "ai": "Prefer 'ai_image' for every scene.",
    }[req.visual_style]
    research = "\n".join(
        f"[{i + 1}] {n['title']}: {n['snippet']}" for i, n in enumerate(notes)
    ) or "(no research available - stay general and avoid specific statistics)"
    return f"""TOPIC / PROMPT: {req.topic}
TARGET COMMUNITY: {req.community}
TONE: {req.tone}
LANGUAGE: {LANGUAGE_RULES[req.language]}
LENGTH: about {req.target_seconds} seconds = about {words} spoken words in total, across {n_scenes} scenes.
VISUAL STYLE: {style}

RESEARCH NOTES:
{research}"""


def write(req: JobRequest, notes: list[dict]) -> ScenePlan:
    try:
        data, provider = chat_json(SYSTEM, _brief(req, notes))
        plan = _to_plan(data, notes, provider)
        return plan
    except (LLMUnavailable, ValidationError, KeyError, TypeError, ValueError) as e:
        log.warning("LLM script unavailable (%s); using offline template", e)
        return offline_plan(req, notes)


def revise(req: JobRequest, notes: list[dict], plan: ScenePlan, issues: list[str]) -> ScenePlan:
    user = (
        _brief(req, notes)
        + "\n\nCURRENT DRAFT:\n"
        + json.dumps(plan.model_dump(exclude={"sources", "generated_by"}), ensure_ascii=False)
        + "\n\nEDITOR FEEDBACK - fix every point, keep what works:\n- "
        + "\n- ".join(issues)
    )
    try:
        data, provider = chat_json(SYSTEM, user, temperature=0.6)
        return _to_plan(data, notes, provider)
    except (LLMUnavailable, ValidationError, KeyError, TypeError, ValueError) as e:
        log.warning("Revision failed (%s); keeping previous draft", e)
        return plan


def _to_plan(data: dict, notes: list[dict], provider: str) -> ScenePlan:
    for i, s in enumerate(data.get("scenes", []), start=1):
        s["id"] = i
        vis = s.get("visual") or {}
        if vis.get("mode") not in ("stock", "ai_image"):
            vis["mode"] = "stock"
        s["visual"] = vis
    if data.get("scenes"):
        data["hook"] = data["scenes"][0]["voiceover"]
    data["sources"] = [{"title": n["title"], "url": n["url"]} for n in notes if n.get("url")]
    data["generated_by"] = provider
    return ScenePlan.model_validate(data)


# ------------------------------------------------------------------ offline
def _sentences(notes: list[dict]) -> list[str]:
    out = []
    for n in notes:
        for s in re.split(r"(?<=[.!?])\s+", n.get("snippet", "")):
            s = s.strip()
            if 8 <= len(s.split()) <= 26 and "(" not in s:
                out.append(s)
    return out


def offline_plan(req: JobRequest, notes: list[dict]) -> ScenePlan:
    """Deterministic, template-based plan so the pipeline works with no LLM key."""
    t = req.topic.strip().rstrip("?.!")
    tw = t.split()
    t_short = " ".join(tw[:8])
    short = " ".join(w for w in tw if w.lower() not in {"how", "to", "the", "a", "an", "in", "of", "for", "why", "what"})[:40] or t_short
    facts = _sentences(notes)[:3]

    if req.language == "hinglish":
        hook = f"{t_short} — ye baat koi nahi batata."
        steps = [
            "Step one: sabse important cheez pe focus karo, baaki sab baad mein.",
            "Step two: chhota start karo. Ek clear step, das vague plans se better hai.",
            "Step three: consistent raho. Roz thoda progress, bada result.",
        ]
        cta = f"Save karo, apni {req.community} community ke saath share karo, aur Qoneqt pe follow karo."
    elif req.language == "hindi":
        hook = f"{t_short} — यह बात कोई नहीं बताता।"
        steps = [
            "पहला कदम: सबसे ज़रूरी चीज़ पर ध्यान दो, बाकी सब बाद में।",
            "दूसरा कदम: छोटी शुरुआत करो। एक साफ़ कदम, दस अधूरे प्लान से बेहतर है।",
            "तीसरा कदम: रोज़ थोड़ा करो। छोटी प्रगति, बड़ा नतीजा।",
        ]
        cta = f"सेव करो, {req.community} कम्युनिटी के साथ शेयर करो, और Qoneqt पर फॉलो करो।"
    else:
        hook = f"{t_short}: here's what most people miss."
        steps = [
            "Step one: get clear on the single thing that matters most right now.",
            "Step two: start small. One clear action beats ten vague plans.",
            "Step three: stay consistent. Tiny progress every day adds up fast.",
        ]
        cta = f"Save this, share it with your {req.community} crew, and follow for more on Qoneqt."
    body = facts or steps
    caps = {
        "hindi": ["यह कोई नहीं बताता", "पहला कदम: फोकस", "दूसरा कदम: छोटी शुरुआत", "तीसरा कदम: रोज़ करो", "अब आपकी बारी"],
        "hinglish": ["Ye koi nahi batata", "Step 1: focus", "Step 2: chhota start", "Step 3: consistent raho", "Ab tumhari baari"],
    }.get(req.language, ["Nobody tells you this", "Step 1: get clear", "Step 2: start small", "Step 3: stay consistent", "Your move"])
    step_caps = caps[1:4]

    scenes = [{"id": 1, "voiceover": hook, "caption": caps[0],
               "visual": {"mode": "ai_image", "query": short, "prompt": f"{t}, dramatic cinematic concept art"}}]
    for i, line in enumerate(body, start=2):
        scenes.append({
            "id": i,
            "voiceover": line,
            "caption": " ".join(line.split()[:4]) if facts else step_caps[min(i - 2, 2)],
            "visual": {"mode": "stock" if i % 2 == 0 else "ai_image", "query": short, "prompt": f"{t}, {line[:80]}"},
        })
    scenes.append({"id": len(scenes) + 1, "voiceover": cta, "caption": caps[4],
                   "visual": {"mode": "stock", "query": "friends looking at phone", "prompt": "friends sharing a phone, warm light"}})

    tag = re.sub(r"[^A-Za-z0-9]", "", short.title())[:24] or "Qoneqt"
    return ScenePlan.model_validate({
        "title": t[:70],
        "hook": hook,
        "hook_options": [hook],
        "scenes": scenes,
        "cta": cta,
        "description": f"{t} — explained in under a minute for the {req.community} community.",
        "hashtags": [f"#{tag}", "#Qoneqt", f"#{re.sub(r'[^A-Za-z0-9]', '', req.community) or 'Community'}", "#LearnOnQoneqt"],
        "sources": [{"title": n["title"], "url": n["url"]} for n in notes if n.get("url")],
        "generated_by": "offline-template",
    })
