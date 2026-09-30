"""FFmpeg composition: scene clips -> concatenated reel -> mixed + loudness-normalised MP4."""
from __future__ import annotations

import hashlib
import random
from pathlib import Path

from .. import config
from . import ff

W, H, FPS = config.WIDTH, config.HEIGHT, config.FPS
VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS)]
AENC = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def render_scene(idx: int, visual: dict, audio_path: str, captions_list: Path, duration: float, out: Path) -> Path:
    """One scene: background (video or Ken-Burns image) + caption overlay + narration."""
    D = f"{duration:.3f}"
    if visual["kind"] == "video":
        bg_in = ["-stream_loop", "-1", "-i", visual["path"]]
        bg = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"
    else:
        bg_in = ["-loop", "1", "-framerate", str(FPS), "-i", visual["path"]]
        sw, sh = int(W * 1.14) // 2 * 2, int(H * 1.14) // 2 * 2
        # slow pan; direction alternates per scene so cuts feel alive
        x = f"(in_w-{W})*t/{D}" if idx % 2 == 0 else f"(in_w-{W})*(1-t/{D})"
        bg = (
            f"[0:v]scale={sw}:{sh}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:x='{x}':y='(in_h-{H})/2',setsar=1,fps={FPS}"
        )
    graph = (
        f"{bg},vignette=PI/5,format=yuv420p[bg];"
        f"[bg][1:v]overlay=0:0:format=auto:shortest=0,format=yuv420p[v];"
        f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=0:{D},asetpts=N/SR/TB[a]"
    )
    ff.run([
        *bg_in,
        "-f", "concat", "-safe", "0", "-i", str(captions_list),
        "-i", audio_path,
        "-filter_complex", graph,
        "-map", "[v]", "-map", "[a]",
        "-t", D, *VENC, *AENC, str(out),
    ])
    return out


def _pick_music(seed: str) -> Path | None:
    tracks = sorted(p for p in config.MUSIC_DIR.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"})
    if not tracks:
        return None
    return random.Random(int(hashlib.md5(seed.encode()).hexdigest(), 16)).choice(tracks)


def assemble(scene_clips: list[Path], out: Path, work: Path, seed: str) -> Path:
    lst = work / "scenes.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in scene_clips), encoding="utf-8")
    joined = work / "joined.mp4"
    ff.run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])

    music = _pick_music(seed)
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if music:
        total = ff.duration(str(joined))
        graph = (
            f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.10,atrim=0:{total:.2f},"
            f"afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5[m];"
            f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,{loud}[a]"
        )
        args = ["-i", str(joined), "-stream_loop", "-1", "-i", str(music), "-filter_complex", graph]
    else:
        args = ["-i", str(joined), "-filter_complex", f"[0:a]{loud}[a]"]
    ff.run([*args, "-map", "0:v", "-map", "[a]", "-c:v", "copy", *AENC, "-movflags", "+faststart", str(out)])
    return out


def thumbnail(video: Path, out: Path, at: float = 0.9) -> Path:
    ff.run(["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)])
    return out
