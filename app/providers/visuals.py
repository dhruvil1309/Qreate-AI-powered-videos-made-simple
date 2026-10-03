"""Per-scene visuals with a fallback chain.

  stock     -> Pexels portrait video -> Pexels photo -> AI image -> generated card
  ai_image  -> Pollinations (Flux) AI image -> Pexels photo -> generated card

Every result is cached on disk by a hash of its request, so regenerating one
scene or re-running a job never pays for the same asset twice.
"""
from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
import urllib.parse
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import config
from ..models import Scene
from . import wan

log = logging.getLogger("qreate.visuals")

PALETTES = [
    ((46, 16, 101), (124, 58, 237)),
    ((17, 24, 39), (91, 33, 182)),
    ((76, 29, 149), (219, 39, 119)),
    ((30, 27, 75), (14, 116, 144)),
    ((49, 46, 129), (147, 51, 234)),
    ((88, 28, 135), (234, 88, 12)),
]


_POLLINATIONS_LOCK = threading.Lock()


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _download(url: str, dest: Path, headers: dict | None = None, timeout: float = 90) -> Path:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if not (ctype.startswith("image") or ctype.startswith("video") or ctype == "application/octet-stream"):
            raise ValueError(f"Unexpected content-type {ctype}")
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
    if tmp.stat().st_size < 5_000:
        tmp.unlink(missing_ok=True)
        raise ValueError("Downloaded file too small")
    tmp.rename(dest)
    return dest


# ---------------------------------------------------------------- Pexels
def _pexels_video(query: str, variant: int = 0) -> dict | None:
    if not config.PEXELS_API_KEY or not query:
        return None
    dest = config.CACHE_DIR / f"pxv_{_key(query, str(variant))}.mp4"
    if dest.exists():
        return {"path": str(dest), "kind": "video", "source": "Pexels video (cached)"}
    r = httpx.get(
        "https://api.pexels.com/videos/search",
        params={"query": query, "orientation": "portrait", "per_page": 8, "size": "medium"},
        headers={"Authorization": config.PEXELS_API_KEY},
        timeout=config.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    videos = videos[variant % len(videos):] + videos[: variant % len(videos)] if videos else []
    for vid in videos:
        files = [
            f for f in vid.get("video_files", [])
            if f.get("height") and f.get("width") and f["height"] >= f["width"] and 1000 <= f["height"] <= 2600
        ]
        if not files:
            continue
        best = min(files, key=lambda f: abs(f["height"] - 1920))
        _download(best["link"], dest)
        credit = vid.get("user", {}).get("name", "Pexels")
        return {"path": str(dest), "kind": "video", "source": f"Pexels video by {credit}", "url": vid.get("url", "")}
    return None


def _pexels_photo(query: str, variant: int = 0) -> dict | None:
    if not config.PEXELS_API_KEY or not query:
        return None
    dest = config.CACHE_DIR / f"pxp_{_key(query, str(variant))}.jpg"
    if dest.exists():
        return {"path": str(dest), "kind": "image", "source": "Pexels photo (cached)"}
    r = httpx.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "orientation": "portrait", "per_page": 5},
        headers={"Authorization": config.PEXELS_API_KEY},
        timeout=config.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        return None
    p = photos[variant % len(photos)]
    _download(p["src"].get("portrait") or p["src"]["large2x"], dest)
    return {"path": str(dest), "kind": "image", "source": f"Pexels photo by {p.get('photographer', 'Pexels')}", "url": p.get("url", "")}


# ---------------------------------------------------------------- AI image
def _pollinations(prompt: str, seed: int) -> dict | None:
    if not config.USE_POLLINATIONS or not prompt:
        return None
    full = f"{prompt}, vertical 9:16 composition, high detail, cinematic lighting, no text, no watermark"
    dest = config.CACHE_DIR / f"ai_{_key(full, str(seed))}.jpg"
    if dest.exists():
        return {"path": str(dest), "kind": "image", "source": "AI image (cached)"}
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(full)
        + f"?width={config.WIDTH}&height={config.HEIGHT}&nologo=true&seed={seed}&model={config.POLLINATIONS_MODEL}"
    )
    # The anonymous tier allows roughly one image every 20-30 seconds and answers
    # 402/429 otherwise. Queue scenes behind one lock and wait the limit out,
    # rather than dropping every scene after the first straight to a title card.
    with _POLLINATIONS_LOCK:
        for attempt in range(config.POLLINATIONS_RETRIES + 1):
            try:
                _download(url, dest, timeout=120)
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (402, 429) or attempt == config.POLLINATIONS_RETRIES:
                    raise
                log.info("Pollinations rate limit; retrying in %ss", config.POLLINATIONS_WAIT)
                time.sleep(config.POLLINATIONS_WAIT)
    Image.open(dest).verify()  # make sure it is a real image
    return {"path": str(dest), "kind": "image", "source": f"AI image ({config.POLLINATIONS_MODEL} via Pollinations)"}


# ---------------------------------------------------------------- Offline card
def generated_card(text: str, idx: int, dest: Path) -> dict:
    """A designed gradient background so the pipeline never fails for lack of visuals."""
    W, H = config.WIDTH, config.HEIGHT
    top, bottom = PALETTES[idx % len(PALETTES)]
    strip = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        strip.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img = strip.resize((W, H))
    rnd = random.Random(idx * 7919 + len(text))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for _ in range(4):
        r = rnd.randint(220, 520)
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, rnd.randint(18, 40)))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), glow)

    # concentric rings: a quiet texture that never competes with the captions
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = rnd.choice([(W * 0.85, H * 0.42), (W * 0.15, H * 0.55), (W * 0.5, H * 0.48)])
    for k in range(6):
        r = 160 + k * 120
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 26 - k * 3), width=3)
    img = Image.alpha_composite(img, layer)
    img.convert("RGB").save(dest, quality=92)
    return {"path": str(dest), "kind": "image", "source": "Generated title card"}


def get_visual(scene: Scene, style: str, job_dir: Path, idx: int, seed: int, variant: int = 0) -> dict:
    """Return {path, kind: image|video, source}. Never raises."""
    v = scene.visual
    query = v.query or v.prompt or scene.caption
    prompt = v.prompt or f"{v.query or scene.caption}, photorealistic"
    want_ai = style == "ai" or (style == "mix" and v.mode == "ai_image")

    chain = []
    if not config.OFFLINE_MODE:
        if want_ai:
            chain = [
                lambda: wan.generate(prompt, job_dir / f"wan_{idx:02d}_{variant}.mp4", seed + variant),
                lambda: _pollinations(prompt, seed + variant),
                lambda: _pexels_photo(query, variant),
                lambda: _pexels_video(query, variant),
            ]
        else:
            chain = [lambda: _pexels_video(query, variant), lambda: _pexels_photo(query, variant), lambda: _pollinations(prompt, seed + variant)]
    for fn in chain:
        try:
            res = fn()
            if res:
                return res
        except Exception as e:  # noqa: BLE001
            log.warning("visual source failed for scene %s: %s", scene.id, e)
    dest = job_dir / f"card_{idx:02d}.jpg"
    return generated_card(v.query or scene.caption, idx + variant, dest)
