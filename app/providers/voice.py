"""Narration with word-level timestamps (used for synced captions).

  0. Sarvam (TTS_PROVIDER=sarvam): Indian-language neural voices (bulbul).
     Saves voice.wav (used in the video) plus voice.mp3. Word timings estimated.
  1. edge-tts: free Microsoft neural voices incl. Indian English and Hindi,
     returns exact word boundaries. Needs internet, no key.
  2. espeak-ng: fully offline, robotic but reliable. Word timings estimated.
  3. silence: last resort so a render never fails; captions still time correctly.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import shutil
import subprocess
import time
import wave
from pathlib import Path

import httpx

from .. import config
from ..media import ff

log = logging.getLogger("qreate.voice")

ESPEAK_VOICES = {"english": "en-us", "hinglish": "en-us", "hindi": "hi"}


def _estimate_words(text: str, total: float, lead: float = 0.05) -> list[dict]:
    words = text.split()
    if not words:
        return []
    weights = [len(w) + 2 for w in words]
    span = max(total - lead - 0.1, 0.5)
    t, out = lead, []
    for w, wt in zip(words, weights):
        d = span * wt / sum(weights)
        out.append({"word": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


async def _edge(text: str, voice: str, dest: Path) -> list[dict]:
    import edge_tts

    try:
        comm = edge_tts.Communicate(text, voice, rate="+8%", boundary="WordBoundary")
    except TypeError:  # older edge-tts versions emit word boundaries by default
        comm = edge_tts.Communicate(text, voice, rate="+8%")
    words = []
    with open(dest, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"word": chunk["text"], "start": round(start, 3), "end": round(start + chunk["duration"] / 1e7, 3)})
    return words


def _sarvam(text: str, language: str, dest: Path) -> None:
    body = {
        "text": text,
        "target_language_code": config.SARVAM_LANGUAGES.get(language, "en-IN"),
        "model": config.SARVAM_TTS_MODEL,
        "speaker": config.SARVAM_TTS_SPEAKER,
        "pace": config.SARVAM_TTS_PACE,
        "speech_sample_rate": 48000,
        "output_audio_codec": "wav",
    }
    for attempt in range(3):
        r = httpx.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": config.SARVAM_API_KEY},
            json=body,
            timeout=config.HTTP_TIMEOUT,
        )
        if r.status_code in (429, 500, 502, 503) and attempt < 2:
            time.sleep(1.5 * (attempt + 1))  # scenes are voiced in parallel; back off on rate limits
            continue
        if r.is_error:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        dest.write_bytes(base64.b64decode(r.json()["audios"][0]))
        return


def synthesize(text: str, language: str, dest_base: Path) -> dict:
    """Return {path, duration, words, engine}. Never raises."""
    text = " ".join(text.split())
    if config.TTS_PROVIDER == "sarvam" and config.SARVAM_API_KEY and not config.OFFLINE_MODE:
        dest = dest_base.with_suffix(".wav")
        try:
            _sarvam(text, language, dest)
            with wave.open(str(dest)) as w:
                dur = w.getnframes() / w.getframerate()
            if dur > 0.3:
                out = {"path": str(dest), "duration": dur, "words": _estimate_words(text, dur),
                       "engine": f"sarvam ({config.SARVAM_TTS_MODEL})"}
                try:
                    mp3 = dest_base.with_suffix(".mp3")
                    ff.run(["-i", str(dest), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)])
                    out["mp3"] = str(mp3)
                except Exception as e:  # noqa: BLE001 - the wav is what the video uses
                    log.warning("mp3 export failed (%s); keeping wav only", e)
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("Sarvam TTS failed (%s); falling back", e)

    if config.USE_EDGE_TTS and not config.OFFLINE_MODE:
        dest = dest_base.with_suffix(".mp3")
        try:
            words = asyncio.run(_edge(text, config.VOICES.get(language, config.VOICES["english"]), dest))
            dur = ff.duration(str(dest))
            if dur > 0.3:
                if not words:
                    words = _estimate_words(text, dur)
                return {"path": str(dest), "duration": dur, "words": words, "engine": "edge-tts"}
        except Exception as e:  # noqa: BLE001
            log.warning("edge-tts failed (%s); falling back", e)

    if shutil.which("espeak-ng"):
        dest = dest_base.with_suffix(".wav")
        try:
            subprocess.run(
                ["espeak-ng", "-v", ESPEAK_VOICES.get(language, "en-us"), "-s", "165", "-p", "45", "-w", str(dest), text],
                check=True, capture_output=True, timeout=60,
            )
            dur = ff.duration(str(dest))
            return {"path": str(dest), "duration": dur, "words": _estimate_words(text, dur), "engine": "espeak-ng"}
        except Exception as e:  # noqa: BLE001
            log.warning("espeak-ng failed (%s); using silence", e)

    dest = dest_base.with_suffix(".wav")
    dur = max(1.5, len(text.split()) / 2.6)
    ff.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{dur:.2f}", str(dest)])
    return {"path": str(dest), "duration": dur, "words": _estimate_words(text, dur), "engine": "silent"}
