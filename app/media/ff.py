"""Thin wrappers around ffmpeg / ffprobe."""
from __future__ import annotations

import json
import subprocess


class FFmpegError(RuntimeError):
    pass


def run(args: list[str], timeout: int = 600) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise FFmpegError(p.stderr[-2000:] or "ffmpeg failed")
    return p.stderr


def run_capture_stderr(args: list[str], timeout: int = 600) -> str:
    """Run ffmpeg with info logging (used by analysis filters like blackdetect)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.stderr


def probe(path: str) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise FFmpegError(p.stderr)
    return json.loads(p.stdout)


def duration(path: str) -> float:
    return float(probe(path)["format"]["duration"])
