"""Word-synced animated captions rendered as transparent PNG frames.

For each scene we emit a list of (png, seconds) states. Each state shows the
scene headline at the top and the current 1-3 word subtitle chunk, with the
word being spoken highlighted. FFmpeg's concat demuxer then turns the list
into an overlay track. Rendering with PIL avoids libass/drawtext font and
escaping problems across machines.
"""
from __future__ import annotations

import re
import textwrap
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

from .. import config

W, H = config.WIDTH, config.HEIGHT
PURPLE = (109, 40, 217, 235)
WHITE = (255, 255, 255, 255)
HILITE = (253, 224, 71, 255)
STROKE = (12, 8, 28, 255)

HEADLINE_Y = 250
SUB_Y = 1180  # keeps text inside the safe zone above the feed's action bar


@lru_cache(maxsize=32)
def _font(size: int, devanagari: bool = False) -> ImageFont.FreeTypeFont:
    path = config.FONT_DEVANAGARI if devanagari and Path(config.FONT_DEVANAGARI).exists() else config.FONT_BOLD
    kwargs = {}
    if devanagari and features.check("raqm"):
        kwargs["layout_engine"] = ImageFont.Layout.RAQM
    try:
        return ImageFont.truetype(path, size, **kwargs)
    except OSError:
        # Pillow's bare default is a ~10px bitmap font, which makes captions
        # unreadable on a 1080x1920 frame. Ask for its scalable face instead.
        return ImageFont.load_default(size)


def _is_devanagari(text: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", text))


def _chunks(words: list[dict], max_words: int = 3) -> list[list[dict]]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or re.search(r"[.,!?;:]$", w["word"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _headline(draw: ImageDraw.ImageDraw, text: str, community: str) -> None:
    dev = _is_devanagari(text)
    if community:
        f = _font(38)
        tag = f"#{re.sub(r'[^A-Za-z0-9]', '', community) or 'Qoneqt'}  on Qoneqt"
        tw = draw.textlength(tag, font=f)
        draw.rounded_rectangle([70, 130, 70 + tw + 48, 190], radius=30, fill=(0, 0, 0, 120))
        draw.text((94, 136), tag, font=f, fill=WHITE)
    if not text:
        return
    text = text if dev else text.upper()
    size, f = 76, _font(76, dev)
    while draw.textlength(text, font=f) > 940 and size > 60:
        size -= 4
        f = _font(size, dev)
    if draw.textlength(text, font=f) <= 940:
        lines = [text]
    else:  # balanced two-line wrap avoids a lonely last word
        size, f = 76, _font(76, dev)
        lines = textwrap.wrap(text, max(10, len(text) // 2 + 2))[:3]
        while max(draw.textlength(line, font=f) for line in lines) > 940 and size > 48:
            size -= 4
            f = _font(size, dev)
    line_h = int(size * 1.22)
    y = HEADLINE_Y
    for line in lines:
        tw = draw.textlength(line, font=f)
        x = (W - tw) / 2
        draw.rounded_rectangle([x - 30, y - 12, x + tw + 30, y + line_h], radius=18, fill=PURPLE)
        draw.text((x, y), line, font=f, fill=WHITE)
        y += line_h + 14


def _subtitle(draw: ImageDraw.ImageDraw, chunk: list[dict], active: int) -> None:
    words = [w["word"] for w in chunk]
    dev = _is_devanagari(" ".join(words))
    size = 92
    f = _font(size, dev)
    space = draw.textlength(" ", font=f)
    total = sum(draw.textlength(w, font=f) for w in words) + space * (len(words) - 1)
    while total > 980 and size > 52:
        size -= 6
        f = _font(size, dev)
        space = draw.textlength(" ", font=f)
        total = sum(draw.textlength(w, font=f) for w in words) + space * (len(words) - 1)
    x = (W - total) / 2
    for i, w in enumerate(words):
        draw.text((x, SUB_Y), w, font=f, fill=HILITE if i == active else WHITE, stroke_width=7, stroke_fill=STROKE)
        x += draw.textlength(w, font=f) + space


def render_scene_captions(caption: str, words: list[dict], duration: float, out_dir: Path, community: str = "") -> list[tuple[str, float]]:
    """Return [(png_path, seconds)] covering exactly `duration` seconds."""
    out_dir.mkdir(parents=True, exist_ok=True)
    states: list[tuple[str, float]] = []
    n = 0

    def frame(chunk: list[dict] | None, active: int) -> str:
        nonlocal n
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        _headline(d, caption, community)
        if chunk:
            _subtitle(d, chunk, active)
        p = out_dir / f"c{n:04d}.png"
        img.save(p, compress_level=1)
        n += 1
        return str(p)

    t = 0.0
    first_start = words[0]["start"] if words else duration
    if first_start > 0.02:
        states.append((frame(None, -1), first_start))
        t = first_start
    all_words = [w for w in words if w["word"].strip()]
    chunks = _chunks(all_words)
    flat = [(ci, wi) for ci, c in enumerate(chunks) for wi in range(len(c))]
    for k, (ci, wi) in enumerate(flat):
        w = chunks[ci][wi]
        nxt = chunks[flat[k + 1][0]][flat[k + 1][1]]["start"] if k + 1 < len(flat) else duration
        dur = max(0.04, min(nxt, duration) - max(t, w["start"]))
        states.append((frame(chunks[ci], wi), dur))
        t += dur
        if t >= duration:
            break
    if t < duration - 0.02:
        if states:
            states.append((states[-1][0], duration - t))
        else:
            states.append((frame(None, -1), duration))
    return states


def write_concat_list(states: list[tuple[str, float]], path: Path) -> Path:
    lines = []
    for p, d in states:
        lines.append(f"file '{p}'")
        lines.append(f"duration {d:.3f}")
    lines.append(f"file '{states[-1][0]}'")  # concat demuxer needs the last file repeated
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
