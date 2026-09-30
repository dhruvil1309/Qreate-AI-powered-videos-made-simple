"""Automated QA gate: technical checks on the render + editorial checks on the plan."""
from __future__ import annotations

import re
from pathlib import Path

from .. import config
from ..models import Critique, ScenePlan
from . import ff


def _check(name: str, ok: bool, detail: str, blocking: bool = True) -> dict:
    return {"check": name, "pass": bool(ok), "detail": detail, "blocking": blocking}


def run_qa(video: Path, plan: ScenePlan, critique: Critique | None, target_seconds: int) -> dict:
    checks = []
    info = ff.probe(str(video))
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])
    size_mb = int(info["format"]["size"]) / 1e6

    checks.append(_check("Vertical 1080×1920", bool(v) and v["width"] == config.WIDTH and v["height"] == config.HEIGHT,
                         f"{v['width']}×{v['height']}" if v else "no video stream"))
    checks.append(_check("H.264 + AAC (feed compatible)", bool(v) and v["codec_name"] == "h264" and bool(a) and a["codec_name"] == "aac",
                         f"{v['codec_name'] if v else '-'} / {a['codec_name'] if a else '-'}"))
    lo, hi = max(10, target_seconds * 0.55), target_seconds * 1.6 + 5
    checks.append(_check("Duration fits target", lo <= dur <= hi, f"{dur:.1f}s (target ~{target_seconds}s)"))
    checks.append(_check("File size under 100 MB", size_mb < 100, f"{size_mb:.1f} MB"))

    black = ff.run_capture_stderr(["-i", str(video), "-vf", "blackdetect=d=0.5:pix_th=0.08", "-an", "-f", "null", "-"])
    black_secs = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", black))
    checks.append(_check("No long black frames", black_secs < 1.0, f"{black_secs:.1f}s black"))

    vol = ff.run_capture_stderr(["-i", str(video), "-af", "volumedetect", "-vn", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", vol)
    mean_db = float(m.group(1)) if m else -91.0
    checks.append(_check("Audible narration", mean_db > -45, f"mean volume {mean_db:.1f} dB"))

    hook_words = len(plan.hook.split())
    checks.append(_check("Hook ≤ 14 words", hook_words <= 14, f"{hook_words} words", blocking=False))
    checks.append(_check("Call to action present", bool(plan.cta) or "follow" in plan.scenes[-1].voiceover.lower(), plan.cta[:80] or "-", blocking=False))
    checks.append(_check("Hashtags ready", len(plan.hashtags) >= 2, " ".join(plan.hashtags) or "-", blocking=False))
    if critique:
        checks.append(_check(f"Critic score ≥ {config.CRITIC_THRESHOLD}", critique.overall >= config.CRITIC_THRESHOLD,
                             f"{critique.overall}/10 ({critique.judged_by})", blocking=False))

    passed = all(c["pass"] for c in checks if c["blocking"])
    return {"passed": passed, "duration": round(dur, 2), "checks": checks}
